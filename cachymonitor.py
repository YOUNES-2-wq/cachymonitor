#!/usr/bin/env python3
"""
CachyMonitor — moniteur système gaming (CPU / GPU / RAM / températures / FPS).

Un seul fichier pour Linux ET Windows : chaque lecteur choisit sa source selon
la plateforme, le reste de l'application (interface, thèmes, langues, calculs
de statistiques) est strictement commun.

    Linux    : /proc, /sys (hwmon), nvidia-smi, logs CSV MangoHud
    Windows  : psutil, nvidia-smi, mémoire partagée MSI Afterburner et RTSS

Dépendances : PySide6 partout, plus psutil sous Windows uniquement.
Aucune autre librairie : les graphes sont dessinés au QPainter.

--------------------------------------------------------------------------
MATÉRIEL — ce qui est réellement testé
--------------------------------------------------------------------------
Le code vise tous les matériels, mais il n'a été VÉRIFIÉ que sur :

    CPU AMD Ryzen 5 5600 (k10temp) + GPU NVIDIA RTX 3060 (nvidia-smi)
      · CachyOS / KDE Plasma / Wayland
      · Windows 11 Pro 24H2 + MSI Afterburner / RivaTuner (RTSS 7.x)

Écrit d'après la documentation mais JAMAIS EXÉCUTÉ sur le matériel
correspondant :

  * température CPU Intel      -> capteur « coretemp »        [Linux]
  * GPU AMD (Radeon)           -> pilote amdgpu via /sys      [Linux]
  * GPU Intel (i915 / xe)      -> partiel, /sys               [Linux]
  * GPU non-NVIDIA sous Windows -> capteurs Afterburner       [Windows]

Si vous testez sur l'une de ces configurations, les retours sont les
bienvenus : ouvrez une « issue » avec la sortie de `scripts/hw-report.sh`
(ou simplement une capture de l'application).
https://github.com/YOUNES-2-wq/cachymonitor/issues
--------------------------------------------------------------------------
"""

import os
import re
import sys
import glob
import time
import subprocess
from collections import deque

from PySide6.QtCore import Qt, QThread, Signal, QPointF, QRectF, QSettings, QLocale
from PySide6.QtGui import (
    QPainter, QColor, QPainterPath, QPen, QBrush, QFont, QLinearGradient, QIcon,
    QPalette,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
    QCheckBox, QSpinBox, QSizePolicy, QComboBox, QToolButton, QListView,
)

APP_VERSION = "1.1.0"

IS_WINDOWS = sys.platform.startswith("win")

# Sous Windows, empêche l'apparition d'une fenêtre console à chaque subprocess.
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WINDOWS else {}


# ----------------------------------------------------------------------------- #
#  Configuration
# ----------------------------------------------------------------------------- #

HISTORY = 120          # nombre d'échantillons gardés pour les graphes
GAME_HISTORY = 6000    # échantillons de jeu gardés (100 ms => ~10 min de jeu)
LOG_INTERVAL_MS = 100  # log_interval de MangoHud (repli si 'elapsed' absent du CSV)
# Sous Windows, c'est nous qui échantillonnons RTSS : on vise la même résolution
# que MangoHud (100 ms), sinon les « lows » se calculeraient sur 60 points par
# minute et le 0.1% low ne voudrait plus rien dire.
WIN_POLL_MS = 100
GAME_WARMUP_S = 5.0    # début de session ignoré (lancement + 1er chargement)
GAME_WINDOW_S = 60.0   # fenêtre glissante sur laquelle les « lows » sont calculés
# Une image qui dure plus d'une seconde n'est pas une saccade de jeu : c'est le
# jeu suspendu (alt-tab, pause, chargement). On l'écarte des statistiques, sinon
# elle écrase à elle seule le 0.1% low. Seuil volontairement très conservateur :
# une vraie saccade ressentie reste bien au-dessus de 1 fps.
FREEZE_IGNORE_MS = 1000.0
DEFAULT_INTERVAL_MS = 1000
DEFAULT_FPS_TARGET = 165   # sert d'échelle aux jauges FPS (= fps_limit MangoHud)

# Dossiers où chercher les logs CSV de MangoHud (le plus récent est utilisé).
FPS_LOG_DIRS = [
    os.path.expanduser("~/.local/share/MangoHud/logs"),
    os.path.expanduser("~/mangohud"),
    os.path.expanduser("~/.local/share/MangoHud"),
    os.path.expanduser("~/.local/share/goverlay"),  # output_folder par défaut de Goverlay
    os.path.expanduser("~/.local/share/goverlay/logs"),
    os.getcwd(),
]
FPS_STALE_SECONDS = 5  # au-delà, on considère qu'aucun jeu ne tourne

# Windows : la mémoire partagée d'Afterburner et celle de RivaTuner (RTSS).
AB_SHARED_MEMORY = ("MAHMSharedMemory", "Global\\MAHMSharedMemory")
RTSS_SHARED_MEMORY = ("RTSSSharedMemoryV2", "Global\\RTSSSharedMemoryV2")

# ----------------------------------------------------------------------------- #
#  Langue de l'interface
# ----------------------------------------------------------------------------- #
#
# Les textes sont écrits en anglais dans le code ; TRANSLATIONS donne les autres
# langues, choisies d'après la locale du système. Ajouter une langue = ajouter
# une entrée au dictionnaire, rien d'autre à toucher.

TRANSLATIONS = {
    "fr": {
        # Réglages
        "System": "Système",
        "Dark": "Sombre",
        "Light": "Clair",
        "Interval": "Intervalle",
        "FPS target": "Cible FPS",
        "Theme": "Thème",
        "Language": "Langue",
        "« System » follows the desktop language":
            "« Système » suit la langue du bureau",
        "Always on top": "Au-dessus des autres fenêtres",
        "Measurement refresh rate": "Fréquence de rafraîchissement des mesures",
        "Scales the FPS colours and marks the frametime graph":
            "Sert d'échelle aux couleurs FPS et de repère sur le graphe de frametime",
        "« System » follows the desktop light/dark setting":
            "« Système » suit le thème clair/sombre du bureau",
        # Panneau de jeu
        "IN GAME": "EN JEU",
        "AVERAGE ({win:.0f} s)": "MOYENNE ({win:.0f} s)",
        "No game detected — launch a game with MangoHud":
            "Aucun jeu détecté — lance un jeu avec MangoHud",
        "No game detected — launch a game with RivaTuner (RTSS) running":
            "Aucun jeu détecté — lance un jeu avec RivaTuner (RTSS) actif",
        "Session running": "Session en cours",
        "Last session (ended)": "Dernière session (terminée)",
        "{state} · {mins:.1f} min played · lows over the last {win:.0f} s "
        "· session range {low:.0f}–{high:.0f} fps":
            "{state} · {mins:.1f} min de jeu · lows sur les {win:.0f} dernières s "
            "· extrêmes session {low:.0f}–{high:.0f} fps",
        "Game": "Jeu",
        # Goulot d'étranglement
        "GPU maxed out — GPU-bound": "GPU à fond — limité par le GPU",
        "CPU maxed out — CPU-bound": "CPU à fond — limité par le CPU",
        "Neither CPU nor GPU saturated — limited by FPS cap / vsync":
            "Ni CPU ni GPU saturés — limité par le cap FPS / vsync",
        "Balanced load": "Charge équilibrée",
        # Divers
        "Starting…": "Démarrage…",
        "waiting for data…": "en attente de données…",
        "Updated every {ms} ms": "Mise à jour toutes les {ms} ms",
        "GPU unavailable": "GPU indisponible",
        "GiB": "Gio",
    },
}


# Langues proposées à l'utilisateur. « système » suit la locale du bureau ; les
# autres sont nommées dans leur propre langue (on ne traduit pas un endonyme).
LANG_MODES = ("systeme", "en", "fr")
LANG_LABELS = {"systeme": "System", "en": "English", "fr": "Français"}
DEFAULT_LANG = "systeme"

_strings = {}


def asset_dir():
    """Dossier des ressources (icônes).

    Empaquetée par PyInstaller, l'application tourne depuis une copie extraite
    dans un dossier temporaire dont le chemin est donné par sys._MEIPASS ;
    __file__ n'y désigne alors plus le dossier d'installation.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    return bundled if bundled else os.path.dirname(os.path.abspath(__file__))


def no_game_text():
    """Message « aucun jeu » adapté à l'outil de mesure de la plateforme."""
    if IS_WINDOWS:
        return tr("No game detected — launch a game with RivaTuner (RTSS) running")
    return tr("No game detected — launch a game with MangoHud")


def _system_language():
    """Code de langue sur deux lettres, d'après le système (défaut 'en').

    Les variables d'environnement POSIX sont la référence sous Linux ; Windows
    ne les définit pas, d'où le repli sur la locale que Qt obtient de l'OS.
    """
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(var)
        if value:
            return value.split(":")[0].split(".")[0].split("_")[0].lower()
    name = QLocale.system().name()          # ex. 'fr_FR'
    return name.split("_")[0].lower() if name else "en"


def set_language(mode):
    """Active une langue ('systeme', 'en', 'fr'…). Les textes déjà affichés ne
    changent pas d'eux-mêmes : c'est retext() qui les repose."""
    global _strings
    code = _system_language() if mode == "systeme" else mode
    _strings = TRANSLATIONS.get(code, {})


def tr(text):
    """Texte d'interface traduit ; renvoie l'anglais si la langue est inconnue."""
    return _strings.get(text, text)


set_language(DEFAULT_LANG)


# ----------------------------------------------------------------------------- #
#  Thèmes
# ----------------------------------------------------------------------------- #
#
# Aucune couleur n'est écrite en dur dans le reste du fichier : le code désigne
# un « rôle » (cpu, texte, alerte…) et col() renvoie la teinte du thème actif.
# Changer de thème se résume donc à changer de dictionnaire puis à redessiner.
#
# Le thème clair ne se contente pas d'inverser le fond : les accents y sont
# assombris, sinon un jaune ou un vert pensés pour du noir deviennent illisibles
# sur du blanc.

THEMES = {
    "sombre": {
        "cpu": "#4ca3ff",
        "gpu": "#5ddc7f",
        "ram": "#b48cff",
        "vram": "#ff9d5c",
        "fps": "#ffd23f",
        "ft": "#ff6b8a",    # frametime (les pics = micro-saccades)
        "ok": "#5ddc7f",
        "warn": "#ffb347",
        "bad": "#ff5f56",
        "bg": "#13151b",
        "card": "#1c1f29",
        "text": "#e6e9f0",
        "muted": "#7d8499",
        "ring": "#272b36",   # anneau de fond des jauges
        "border": "#2a2e3a",
    },
    "clair": {
        "cpu": "#1668d0",
        "gpu": "#12833f",
        "ram": "#7343c8",
        "vram": "#c25d0a",
        "fps": "#a6740a",
        "ft": "#cf2f56",
        "ok": "#12833f",
        "warn": "#b06a00",
        "bad": "#c9271c",
        "bg": "#eef1f6",
        "card": "#ffffff",
        "text": "#1b1f2a",
        "muted": "#66707f",
        "ring": "#dde2ec",
        "border": "#ccd3e0",
    },
}

# Modes proposés à l'utilisateur. « système » suit le réglage du bureau.
THEME_MODES = ("systeme", "sombre", "clair")
THEME_LABELS = {"systeme": "System", "sombre": "Dark", "clair": "Light"}
DEFAULT_THEME = "systeme"

_palette = THEMES["sombre"]


def col(role):
    """Couleur du rôle demandé dans le thème actif."""
    return _palette[role]


def set_palette(theme):
    """Active une palette ('sombre' ou 'clair')."""
    global _palette
    _palette = THEMES[theme]


def _windows_light_theme():
    """Réglage clair/sombre de Windows, ou None s'il n'est pas lisible."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return bool(value)
    except Exception:
        return None


def system_theme():
    """Thème du bureau, via Qt. Replié sur 'sombre' si le bureau ne dit rien.

    Qt 6.5+ rapporte le réglage sur les deux plateformes. Quand il répond
    « inconnu » sous Windows, le registre donne la réponse directement.
    """
    scheme = QApplication.instance().styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Light:
        return "clair"
    if scheme == Qt.ColorScheme.Dark:
        return "sombre"
    if IS_WINDOWS:
        light = _windows_light_theme()
        if light is not None:
            return "clair" if light else "sombre"
    return "sombre"


def resolve_theme(mode):
    """Traduit un mode ('systeme'/'sombre'/'clair') en palette réelle."""
    return system_theme() if mode == "systeme" else mode


def temp_role(t):
    """Rôle de couleur d'une température (None = inconnue)."""
    if t is None:
        return "muted"
    if t >= 85:
        return "bad"
    if t >= 70:
        return "warn"
    return "ok"


def _as_bool(v):
    """QSettings rend les booléens en texte selon le backend."""
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return bool(v)


# ----------------------------------------------------------------------------- #
#  Windows — mémoire partagée
# ----------------------------------------------------------------------------- #
#
# Sous Windows il n'existe pas d'équivalent de /sys : les températures et la
# conso ne sont pas lisibles sans pilote. On lit donc les capteurs déjà publiés
# par MSI Afterburner, que le joueur fait tourner de toute façon pour RivaTuner.
# Avantage décisif pour le FPS : c'est la source de l'OSD RTSS, donc l'appli
# affiche exactement le même chiffre que celui vu en jeu.


def _kernel32():
    """kernel32 avec les signatures nécessaires au 64-bit.

    Sans restype/argtypes explicites, ctypes tronque les pointeurs renvoyés par
    MapViewOfFile à 32 bits et le processus meurt en ACCESS_VIOLATION.
    """
    import ctypes
    k32 = ctypes.windll.kernel32
    k32.OpenFileMappingW.restype = ctypes.c_void_p
    k32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
    k32.MapViewOfFile.restype = ctypes.c_void_p
    k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                  ctypes.c_uint32, ctypes.c_size_t]
    k32.UnmapViewOfFile.restype = ctypes.c_bool
    k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    k32.CloseHandle.restype = ctypes.c_bool
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    return k32


def _read_shared_memory(names, size_from_header):
    """Lit une mémoire partagée Windows nommée.

    `size_from_header` reçoit les 64 premiers octets et renvoie la taille totale
    à mapper (ou None pour abandonner) : la taille réelle se trouve dans l'en-tête
    de ces structures, on ne peut pas la connaître avant de l'avoir lue.
    """
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        FILE_MAP_READ = 0x0004
        k32 = _kernel32()

        handle = None
        for name in names:
            h = k32.OpenFileMappingW(FILE_MAP_READ, False, name)
            if h:
                handle = h
                break
        if not handle:
            return None
        try:
            ptr = k32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 64)
            if not ptr:
                return None
            header = bytes(ctypes.string_at(ptr, 64))
            k32.UnmapViewOfFile(ptr)

            total = size_from_header(header)
            if not total:
                return None

            ptr = k32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, total)
            if not ptr:
                return None
            data = bytes(ctypes.string_at(ptr, total))
            k32.UnmapViewOfFile(ptr)
            return data
        finally:
            k32.CloseHandle(handle)
    except Exception:
        return None


class AfterburnerReader:
    """Capteurs MSI Afterburner (mémoire partagée « MAHMSharedMemory »).

    Structure MAHM_SHARED_MEMORY :
      en-tête : dwSignature('MAHM') dwVersion dwHeaderSize dwNumEntries dwEntrySize
      entrée  : szSrcName[260] szSrcUnits[260] szLocalizedSrcName[260]
                szLocalizedSrcUnits[260] szRecommendedFormat[260] float data …
    """

    SIGNATURE = 0x4D41484D          # 'MAHM'
    NAME_LEN = 260
    DATA_OFF = NAME_LEN * 5         # le float 'data' suit les cinq chaînes
    NA = 1e30                       # capteur inactif = FLT_MAX, pas 0

    def __init__(self):
        self._cache = {}
        self._cache_time = 0.0

    def read(self):
        """{nom_capteur: valeur}. Caché brièvement : plusieurs lecteurs
        l'interrogent au même tick (CPU, GPU, FPS)."""
        if time.monotonic() - self._cache_time < 0.4:
            return self._cache
        self._cache = self._read_sensors()
        self._cache_time = time.monotonic()
        return self._cache

    def available(self):
        """True si Afterburner tourne et publie ses capteurs."""
        return bool(self.read())

    def get(self, *names):
        """Première valeur exploitable parmi plusieurs noms de capteurs."""
        sensors = self.read()
        for name in names:
            value = sensors.get(name)
            if value is not None:
                return value
        return None

    def _read_sensors(self):
        import struct

        def total_size(header):
            sig, _ver, hdr_sz, count, entry_sz = struct.unpack_from("<IIIII", header, 0)
            if (sig != self.SIGNATURE or hdr_sz > 4096
                    or not 0 < count <= 1024
                    or not self.DATA_OFF + 4 <= entry_sz <= 65536):
                return None
            self._layout = (hdr_sz, count, entry_sz)
            return hdr_sz + count * entry_sz

        self._layout = None
        data = _read_shared_memory(AB_SHARED_MEMORY, total_size)
        if not data or not self._layout:
            return {}

        hdr_sz, count, entry_sz = self._layout
        sensors = {}
        for i in range(count):
            base = hdr_sz + i * entry_sz
            if base + entry_sz > len(data):
                break
            name = data[base:base + self.NAME_LEN].split(b"\0")[0]
            if not name:
                continue
            value = struct.unpack_from("<f", data, base + self.DATA_OFF)[0]
            if value != value or abs(value) >= self.NA:   # NaN ou FLT_MAX
                continue
            sensors[name.decode("latin-1")] = value
        return sensors


# Instance partagée : CPU, GPU et FPS viennent tous de la même lecture.
AB = AfterburnerReader()


# ----------------------------------------------------------------------------- #
#  Lecture des capteurs
# ----------------------------------------------------------------------------- #

def _find_hwmon(name):
    """Renvoie le chemin d'un hwmon par son nom (ex: 'k10temp')."""
    if IS_WINDOWS:
        return None
    for path in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            with open(os.path.join(path, "name")) as f:
                if f.read().strip() == name:
                    return path
        except OSError:
            continue
    return None


def _read_first(path, default=None):
    """Lit un fichier sysfs et renvoie son contenu nettoyé (ou default)."""
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, ValueError):
        return default


# Pilotes de température CPU, par ordre de préférence.
#   k10temp  : AMD (Zen / Ryzen / Threadripper)
#   zenpower : pilote AMD alternatif (paquet AUR)
#   coretemp : Intel
#   cpu_thermal / acpitz : repli générique (ARM, machines virtuelles, portables)
CPU_TEMP_DRIVERS = ("k10temp", "zenpower", "coretemp", "cpu_thermal", "acpitz")

# Libellés de capteurs correspondant à la température « globale » du CPU.
#   Tctl/Tdie  : AMD          Package id 0 : Intel
CPU_TEMP_LABELS = ("tctl", "tdie", "package id 0", "cpu")


def find_cpu_temp_file():
    """Trouve le fichier sysfs de la température CPU, quel que soit le matériel (Linux).

    On cherche un pilote connu (AMD, Intel, générique), puis dans ce pilote le
    capteur qui représente le processeur entier plutôt qu'un cœur isolé : son
    libellé (tempN_label) vaut Tctl/Tdie chez AMD, « Package id 0 » chez Intel.
    Sans libellé exploitable, on retombe sur temp1_input.
    """
    if IS_WINDOWS:
        return None
    for driver in CPU_TEMP_DRIVERS:
        hw = _find_hwmon(driver)
        if not hw:
            continue
        # 1) On privilégie le capteur « paquet » via son libellé.
        for label_file in sorted(glob.glob(os.path.join(hw, "temp*_label"))):
            label = (_read_first(label_file) or "").lower()
            if any(k in label for k in CPU_TEMP_LABELS):
                cand = label_file.replace("_label", "_input")
                if os.path.exists(cand):
                    return cand
        # 2) Sinon, le premier capteur disponible.
        for cand in sorted(glob.glob(os.path.join(hw, "temp*_input"))):
            return cand
    return None


class CpuReader:
    """Usage CPU (total + par cœur), fréquence et température."""

    def __init__(self):
        if IS_WINDOWS:
            # psutil.cpu_percent() compare deux appels : le premier amorce le
            # compteur, sinon le tout premier échantillon vaudrait 0 %.
            try:
                import psutil
                psutil.cpu_percent(interval=None)
                psutil.cpu_percent(percpu=True, interval=None)
            except ImportError:
                pass
            self._temp_cache = None
            self._temp_cache_time = 0.0
            self._temp_file = None
            return
        self._prev = self._read_stat()
        # Détection indépendante du constructeur (AMD, Intel, générique).
        self._temp_file = find_cpu_temp_file()

    @staticmethod
    def _read_stat():
        totals = {}
        with open("/proc/stat") as f:
            for line in f:
                if not line.startswith("cpu"):
                    break
                parts = line.split()
                key = parts[0]
                vals = list(map(int, parts[1:]))
                idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                total = sum(vals)
                totals[key] = (idle, total)
        return totals

    def _usage(self):
        cur = self._read_stat()
        out = {}
        for key, (idle, total) in cur.items():
            pidle, ptotal = self._prev.get(key, (idle, total))
            dt = total - ptotal
            di = idle - pidle
            out[key] = max(0.0, min(100.0, 100.0 * (1 - di / dt))) if dt > 0 else 0.0
        self._prev = cur
        return out

    @staticmethod
    def _freq_mhz():
        files = glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")
        vals = []
        for fp in files:
            try:
                with open(fp) as f:
                    vals.append(int(f.read()) / 1000.0)  # kHz -> MHz
            except (OSError, ValueError):
                pass
        return sum(vals) / len(vals) if vals else None

    def _temp(self):
        if not self._temp_file:
            return None
        try:
            with open(self._temp_file) as f:
                return int(f.read()) / 1000.0
        except (OSError, ValueError):
            return None

    def _temp_win(self):
        """Température CPU sous Windows — cinq sources, dans cet ordre :

          1. MSI Afterburner (mémoire partagée)  — instantané, déjà lancé
          2. LibreHardwareMonitor HTTP           — View > Options > Remote Web Server
          3. LibreHardwareMonitor WMI            — View > Options > WMI Server
          4. OpenHardwareMonitor WMI
          5. MSAcpi_ThermalZoneTemperature       — souvent réservé à l'administrateur

        Seule la première est assez rapide pour chaque tick ; les autres passent
        par HTTP ou PowerShell et sont donc mises en cache 5 secondes.
        """
        temp = AB.get("CPU temperature")
        if temp is not None and 0 < temp < 150:
            return temp

        if time.time() - self._temp_cache_time < 5.0:
            return self._temp_cache

        temp = None
        try:
            import urllib.request
            import json
            with urllib.request.urlopen("http://localhost:8085/data.json",
                                        timeout=1) as resp:
                tree = json.loads(resp.read())

            def find_temp(node):
                label = node.get("Text", "").lower()
                value = node.get("Value", "")
                if "°c" in value.lower() and any(
                    k in label for k in ("cpu package", "core (max)", "tdie",
                                         "tctl", "cpu core", "core max")
                ):
                    t = _num(value.split("°")[0].strip().replace(",", "."))
                    if t is not None and 0 < t < 150:
                        return t
                for child in node.get("Children", []):
                    found = find_temp(child)
                    if found is not None:
                        return found
                return None

            temp = find_temp(tree)
        except Exception:
            pass

        def powershell(command):
            try:
                return subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                    capture_output=True, text=True, timeout=3, **_NO_WINDOW,
                ).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                return ""

        for namespace in ("root/LibreHardwareMonitor", "root/OpenHardwareMonitor"):
            if temp is not None:
                break
            temp = _num(powershell(
                f"Get-WmiObject -Namespace '{namespace}' -Class Sensor "
                "-ErrorAction SilentlyContinue | "
                "Where-Object {$_.SensorType -eq 'Temperature' -and "
                "$_.Name -match 'CPU Package|Core .Max.'} | "
                "Sort-Object Value -Descending | "
                "Select-Object -First 1 -ExpandProperty Value"
            ))

        if temp is None:
            # MSAcpi rend des dixièmes de kelvin.
            raw = _num(powershell(
                "(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi "
                "-ErrorAction SilentlyContinue | Sort-Object CurrentTemperature "
                "-Descending | Select-Object -First 1).CurrentTemperature"
            ))
            if raw is not None:
                celsius = raw / 10.0 - 273.15
                if 0 < celsius < 150:
                    temp = celsius

        self._temp_cache = temp
        self._temp_cache_time = time.time()
        return temp

    def _sample_win(self):
        try:
            import psutil
            cpu_pct = psutil.cpu_percent(interval=None)
            cpu_cores = psutil.cpu_percent(percpu=True, interval=None)
            freq = psutil.cpu_freq()
            cpu_freq = freq.current if freq else None
        except ImportError:
            cpu_pct, cpu_cores, cpu_freq = 0.0, [], None

        # psutil lit la fréquence *de base* dans le registre, une valeur figée :
        # celle d'Afterburner est la fréquence réelle, boost compris.
        boost = AB.get("CPU clock")
        if boost and 100 < boost < 10000:
            cpu_freq = boost

        return {
            "cpu_pct": cpu_pct,
            "cpu_cores": cpu_cores,
            "cpu_freq": cpu_freq,
            "cpu_temp": self._temp_win(),
            "cpu_power": AB.get("CPU power"),
        }

    def sample(self):
        if IS_WINDOWS:
            return self._sample_win()
        usage = self._usage()
        cores = sorted(
            (k for k in usage if k != "cpu"),
            key=lambda k: int(k[3:]),
        )
        return {
            "cpu_pct": usage.get("cpu", 0.0),
            "cpu_cores": [usage[k] for k in cores],
            "cpu_freq": self._freq_mhz(),
            "cpu_temp": self._temp(),
            "cpu_power": None,
        }


def read_ram():
    if IS_WINDOWS:
        try:
            import psutil
            mem = psutil.virtual_memory()
        except ImportError:
            return {"ram_used": 0.0, "ram_total": 0.0, "ram_pct": 0.0}
        gib = 1024 ** 3
        return {
            "ram_used": mem.used / gib,
            "ram_total": mem.total / gib,
            "ram_pct": mem.percent,
        }

    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, v = line.partition(":")
            info[k] = int(v.split()[0])  # kB
    total = info.get("MemTotal", 0) / 1024 / 1024          # GiB
    avail = info.get("MemAvailable", 0) / 1024 / 1024
    used = total - avail
    pct = (used / total * 100) if total else 0.0
    return {"ram_used": used, "ram_total": total, "ram_pct": pct}


# ----------------------------------------------------------------------------- #
#  Détection du nom du matériel (statique : lu une seule fois au démarrage)
# ----------------------------------------------------------------------------- #

def _clean_cpu(name):
    """Raccourcit le libellé CPU : 'AMD Ryzen 5 5600 6-Core Processor' -> 'AMD Ryzen 5 5600'."""
    name = re.sub(r"\(R\)|\(TM\)|\(tm\)", "", name)
    name = re.sub(r"\s*\d+-Core Processor", "", name)
    name = re.sub(r"@.*$", "", name)
    name = name.replace("Processor", "").replace("CPU", "")
    return " ".join(name.split()) or "CPU"


def read_cpu_name():
    """Nom du processeur (ex: 'AMD Ryzen 5 5600')."""
    if IS_WINDOWS:
        # Le registre répond instantanément, contrairement à WMI — et wmic a été
        # retiré de Windows 11 24H2.
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            winreg.CloseKey(key)
            return _clean_cpu(name)
        except Exception:
            return "CPU"
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return _clean_cpu(line.split(":", 1)[1].strip())
    except OSError:
        pass
    return "CPU"


def _ram_dmi():
    """Type + vitesse RAM via dmidecode, uniquement si accessible sans sudo (sinon None)."""
    try:
        out = subprocess.run(
            ["dmidecode", "-t", "memory"],
            capture_output=True, text=True, timeout=2,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    mtype = speed = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Type:") and "DDR" in line:
            mtype = line.split(":", 1)[1].strip()
        elif line.startswith("Configured Memory Speed:") and "Unknown" not in line:
            speed = line.split(":", 1)[1].strip()
    parts = [p for p in (mtype, speed) if p]
    return " ".join(parts) or None


# Codes SMBIOS des types de mémoire, tels que Win32_PhysicalMemory les rapporte.
SMBIOS_MEMORY_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4",
                       34: "DDR5", 35: "LPDDR4", 37: "LPDDR5"}


def _ram_cim():
    """Type + vitesse RAM via CIM (Windows), ex: 'DDR4 3200 MT/s'."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_PhysicalMemory -ErrorAction SilentlyContinue | "
             "Select-Object -First 1 | ForEach-Object "
             "{ \"$($_.SMBIOSMemoryType) $($_.Speed)\" }"],
            capture_output=True, text=True, timeout=6, **_NO_WINDOW,
        ).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    if len(out) < 2:
        return None
    mtype = SMBIOS_MEMORY_TYPES.get(int(_num(out[0]) or 0))
    speed = _num(out[1])
    parts = [mtype, f"{speed:.0f} MT/s" if speed else None]
    return " ".join(p for p in parts if p) or None


# dmidecode et CIM coûtent cher : la RAM ne change pas en cours de session, on
# ne les interroge donc qu'une fois (read_ram_name est rappelé à chaque
# changement de langue, pour traduire l'unité).
_RAM_EXTRA_UNREAD = object()
_ram_extra_cache = _RAM_EXTRA_UNREAD


def _ram_extra():
    global _ram_extra_cache
    if _ram_extra_cache is _RAM_EXTRA_UNREAD:
        try:
            _ram_extra_cache = _ram_cim() if IS_WINDOWS else _ram_dmi()
        except Exception:
            _ram_extra_cache = None
    return _ram_extra_cache


def read_ram_name():
    """Capacité physique (+ type/vitesse si lisibles), ex: '16 Gio · DDR4 3200 MT/s'."""
    kb = None
    if IS_WINDOWS:
        try:
            import psutil
            kb = psutil.virtual_memory().total / 1024
        except ImportError:
            pass
    else:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        break
        except OSError:
            pass
    if not kb:
        return "RAM"
    gib = kb / 1024 / 1024
    # La capacité « affichée » est < à la capacité physique (kernel, intégré) :
    # on arrondit au multiple de 4 Gio le plus proche pour retomber sur 8/16/32…
    phys = round(gib / 4) * 4 if gib > 6 else round(gib)
    cap = f"{phys} {tr('GiB')}"
    extra = _ram_extra()
    return f"{cap} · {extra}" if extra else cap


# Identifiants PCI des constructeurs de cartes graphiques.
PCI_VENDOR_NVIDIA = "0x10de"
PCI_VENDOR_AMD = "0x1002"
PCI_VENDOR_INTEL = "0x8086"


def _drm_cards():
    """Cartes graphiques vues par le noyau : [(chemin_device, id_constructeur)].

    Note : l'index n'est pas toujours 0 (sur la machine de dev c'est 'card1'),
    d'où le glob plutôt qu'un chemin en dur.
    """
    if IS_WINDOWS:
        return []
    cards = []
    for dev in sorted(glob.glob("/sys/class/drm/card[0-9]*/device")):
        vendor = _read_first(os.path.join(dev, "vendor"))
        if vendor:
            cards.append((dev, vendor.lower()))
    return cards


def _gpu_name_lspci(dev_path, fallback):
    """Nom commercial du GPU via lspci (paquet pciutils, présent par défaut)."""
    slot = os.path.basename(os.path.realpath(dev_path))  # ex: 0000:08:00.0
    if slot.startswith("0000:"):
        slot = slot[5:]
    try:
        out = subprocess.run(["lspci", "-s", slot], capture_output=True,
                             text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return fallback
    # "08:00.0 VGA compatible controller: NVIDIA Corporation GA106 [GeForce RTX 3060]"
    if ":" in out:
        name = out.split(":")[-1].strip()
        # L'ordre compte : on retire d'abord « (rev a1) », sinon l'ancrage de fin
        # de l'expression suivante ne trouve jamais les crochets.
        name = re.sub(r"\s*\(rev [^)]+\)", "", name)
        # lspci met le nom commercial entre crochets :
        #   « Navi 31 [Radeon RX 7900 XTX] » -> « Radeon RX 7900 XTX »
        m = re.search(r"\[([^\]]+)\]\s*$", name)
        if m:
            name = m.group(1)
        for noise in ("Corporation ", "Advanced Micro Devices, Inc. ",
                      "[AMD/ATI] ", "[AMD] ", "Intel Corporation "):
            name = name.replace(noise, "")
        if name:
            return name.strip()
    return fallback


def _hwmon_of(dev_path):
    """hwmon rattaché à une carte (température / conso / fréquence)."""
    for hw in glob.glob(os.path.join(dev_path, "hwmon", "hwmon*")):
        return hw
    return None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _nvidia_smi():
    """Chemin de nvidia-smi. Sous Windows il n'est pas toujours dans le PATH."""
    if IS_WINDOWS:
        import shutil
        if not shutil.which("nvidia-smi"):
            fallback = r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
            if os.path.exists(fallback):
                return fallback
    return "nvidia-smi"


def _gpu_nvidia():
    """GPU NVIDIA via nvidia-smi (usage, temp, VRAM, clock, power)."""
    query = "name,utilization.gpu,temperature.gpu,memory.used,memory.total,clocks.gr,power.draw"
    try:
        out = subprocess.run(
            [_nvidia_smi(), f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4, **_NO_WINDOW,
        ).stdout.strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    fields = [x.strip() for x in out[0].split(",")]
    if len(fields) < 7:
        return None
    return {
        "gpu_name": fields[0],
        "gpu_pct": _num(fields[1]) or 0.0,
        "gpu_temp": _num(fields[2]),
        "vram_used": _num(fields[3]) or 0.0,   # MiB
        "vram_total": _num(fields[4]) or 0.0,
        "gpu_clock": _num(fields[5]),
        "gpu_power": _num(fields[6]),
    }


def _gpu_amd():
    """GPU AMD via le pilote amdgpu, qui expose tout dans /sys (aucun outil externe).

    ⚠️ Écrit d'après la documentation du noyau, NON TESTÉ sur une vraie Radeon
    (machine de développement équipée en NVIDIA). Retours bienvenus.
    """
    for dev, vendor in _drm_cards():
        if vendor != PCI_VENDOR_AMD:
            continue
        busy = _num(_read_first(os.path.join(dev, "gpu_busy_percent")))
        vram_total = _num(_read_first(os.path.join(dev, "mem_info_vram_total")))
        vram_used = _num(_read_first(os.path.join(dev, "mem_info_vram_used")))
        # Une carte AMD sans ces fichiers = pilote trop ancien : on passe.
        if busy is None and vram_total is None:
            continue

        temp = power = clock = None
        hw = _hwmon_of(dev)
        if hw:
            t = _num(_read_first(os.path.join(hw, "temp1_input")))
            temp = t / 1000.0 if t is not None else None          # m°C -> °C
            p = _num(_read_first(os.path.join(hw, "power1_average")))
            if p is None:
                p = _num(_read_first(os.path.join(hw, "power1_input")))
            power = p / 1e6 if p is not None else None            # µW -> W
            f = _num(_read_first(os.path.join(hw, "freq1_input")))
            clock = f / 1e6 if f is not None else None            # Hz -> MHz

        return {
            "gpu_name": _gpu_name_lspci(dev, "AMD GPU"),
            "gpu_pct": busy or 0.0,
            "gpu_temp": temp,
            "vram_used": (vram_used / 1024 / 1024) if vram_used else 0.0,   # octets -> MiB
            "vram_total": (vram_total / 1024 / 1024) if vram_total else 0.0,
            "gpu_clock": clock,
            "gpu_power": power,
        }
    return None


def _gpu_intel():
    """GPU Intel (i915 / xe). Volontairement partiel.

    Le taux d'occupation d'un GPU Intel n'est pas exposé dans /sys : il faut
    intel_gpu_top, qui réclame les privilèges root. On se limite donc à ce qui
    est lisible sans droits particuliers (nom, température, fréquence).
    La VRAM est de la mémoire système partagée : pas de compteur dédié.

    ⚠️ NON TESTÉ sur du matériel Intel. Retours bienvenus.
    """
    for dev, vendor in _drm_cards():
        if vendor != PCI_VENDOR_INTEL:
            continue
        temp = clock = None
        hw = _hwmon_of(dev)
        if hw:
            t = _num(_read_first(os.path.join(hw, "temp1_input")))
            temp = t / 1000.0 if t is not None else None
        f = _num(_read_first(os.path.join(dev, "..", "gt_cur_freq_mhz")))
        if f is None:
            f = _num(_read_first(os.path.join(dev, "gt_cur_freq_mhz")))
        clock = f
        return {
            "gpu_name": _gpu_name_lspci(dev, "Intel GPU"),
            "gpu_pct": 0.0,          # indisponible sans root
            "gpu_temp": temp,
            "vram_used": 0.0,        # mémoire partagée avec la RAM
            "vram_total": 0.0,
            "gpu_clock": clock,
            "gpu_power": None,
        }
    return None


def _gpu_afterburner():
    """GPU via les capteurs Afterburner (Windows, cartes non-NVIDIA).

    Sous Windows, une Radeon ou un iGPU Intel n'expose rien d'équivalent à
    /sys : Afterburner, lui, sait les lire. Le nom commercial ne fait pas
    partie des capteurs, d'où le libellé générique.

    ⚠️ NON TESTÉ sur du matériel AMD/Intel. Retours bienvenus.
    """
    usage = AB.get("GPU usage")
    temp = AB.get("GPU temperature")
    if usage is None and temp is None:
        return None
    return {
        "gpu_name": "GPU",
        "gpu_pct": usage or 0.0,
        "gpu_temp": temp,
        "vram_used": AB.get("Memory usage") or 0.0,   # Mio
        "vram_total": 0.0,                            # non exposé par Afterburner
        "gpu_clock": AB.get("Core clock"),
        "gpu_power": AB.get("Power"),
    }


def read_gpu():
    """Lit le GPU, quel que soit le constructeur.

    On essaie NVIDIA (nvidia-smi), puis AMD et Intel (/sys sous Linux, capteurs
    Afterburner sous Windows). Le premier lecteur qui renvoie quelque chose
    gagne ; si aucun ne répond, l'interface affiche « GPU indisponible » au lieu
    de planter.
    """
    for reader in (_gpu_nvidia, _gpu_amd, _gpu_intel, _gpu_afterburner):
        try:
            data = reader()
        except Exception:
            data = None          # un GPU exotique ne doit jamais faire tomber l'app
        if data:
            return data
    return _gpu_none()


def _gpu_none():
    return {
        "gpu_name": tr("GPU unavailable"), "gpu_pct": 0.0, "gpu_temp": None,
        "vram_used": 0.0, "vram_total": 0.0, "gpu_clock": None, "gpu_power": None,
    }


def _percentile(sorted_vals, q):
    """q dans [0,1]. Renvoie la valeur au quantile q (méthode du plus proche rang)."""
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def game_stats(samples, live, name, extra=None):
    """Statistiques d'une session à partir d'échantillons (t_s, fps, frametime_ms).

    Commun aux deux plateformes : MangoHud et RTSS ne diffèrent que par la façon
    de collecter les échantillons, pas par le sens des chiffres qu'on en tire.
    Les « lows » portent sur une fenêtre glissante des GAME_WINDOW_S dernières
    secondes — sur une session entière, un écran de chargement en milieu de
    partie plomberait définitivement le 0.1% low alors qu'il ne dit rien de la
    fluidité actuelle.
    """
    if not samples:
        return None

    t_end = samples[-1][0]
    window = [s for s in samples if s[0] >= t_end - GAME_WINDOW_S] or list(samples)

    w_fps = [s[1] for s in window]
    vals = sorted(w_fps)
    all_fps = [s[1] for s in samples]
    ft_hist = [s[2] for s in window if s[2] is not None]

    stats = {
        "live": live,
        "name": name,
        "fps": samples[-1][1] if live else None,
        "avg": sum(w_fps) / len(w_fps),
        "low1": _percentile(vals, 0.01),
        "low01": _percentile(vals, 0.001),
        "window_s": min(GAME_WINDOW_S, max(1.0, t_end - window[0][0])),
        "min": min(all_fps),
        "max": max(all_fps),
        "samples": len(samples),
        "duration_s": t_end,
        "frametime": ft_hist[-1] if (live and ft_hist) else None,
        "ft_history": ft_hist,
        "cpu_load": None,
        "gpu_load": None,
        "vram_used": None,
    }
    if extra:
        stats.update(extra)
    return stats


class MangoHudGameReader:
    """Lit une session de jeu depuis le log CSV MangoHud le plus récent (Linux).

    Lecture *incrémentale* (on garde l'offset atteint) pour accumuler les
    échantillons et calculer les métriques qui comptent en jeu : 1% low,
    0.1% low, moyenne et frametimes.

    Deux précautions sur la qualité des données :
      * on ignore les GAME_WARMUP_S premières secondes (lancement du jeu,
        premier chargement : MangoHud y enregistre des images à 0 fps) ;
      * les « lows » sont calculés sur une **fenêtre glissante** des
        GAME_WINDOW_S dernières secondes. Sur une session entière, un écran
        de chargement en milieu de partie plomberait définitivement le
        0.1% low alors qu'il ne dit rien de la fluidité actuelle.
    """

    # Colonnes du CSV MangoHud qui nous intéressent.
    WANTED = ("fps", "frametime", "cpu_load", "gpu_load", "gpu_vram_used", "elapsed")

    def __init__(self):
        self._path = None        # log en cours de suivi
        self._pos = 0            # offset de lecture déjà consommé
        self._cols = None        # nom de colonne -> index
        # échantillons (t_secondes, fps, frametime_ms)
        self._samples = deque(maxlen=GAME_HISTORY)
        self._n = 0              # compteur, sert de repli si 'elapsed' absent
        self._t0 = None          # 'elapsed' de la 1re ligne (en ns)
        self._last = {}          # dernière ligne complète parsée

    # -- helpers ---------------------------------------------------------- #
    @staticmethod
    def _newest_log():
        newest, newest_mtime = None, 0
        for d in FPS_LOG_DIRS:
            for fp in glob.glob(os.path.join(d, "*.csv")):
                try:
                    m = os.path.getmtime(fp)
                except OSError:
                    continue
                if m > newest_mtime:
                    newest, newest_mtime = fp, m
        return newest, newest_mtime

    @staticmethod
    def _game_name(path):
        """urbanterror_2026-07-20_12-40-15.csv -> Urbanterror"""
        base = os.path.basename(path)
        base = re.sub(r"\.csv$", "", base, flags=re.I)
        base = re.sub(r"_\d{4}-\d{2}-\d{2}[_-]\d{2}-\d{2}-\d{2}$", "", base)
        return base.replace("_", " ").strip().title() or tr("Game")

    def _reset_for(self, path):
        self._path = path
        self._pos = 0
        self._cols = None
        self._samples.clear()
        self._n = 0
        self._t0 = None
        self._last = {}

    def _parse_header(self, line):
        cols = [c.strip().lower() for c in line.split(",")]
        if "fps" not in cols:
            return None
        return {name: cols.index(name) for name in self.WANTED if name in cols}

    def _consume(self, path):
        """Lit les nouvelles lignes depuis la dernière position connue."""
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        # Fichier tronqué / recréé : on repart de zéro.
        if size < self._pos:
            self._reset_for(path)
        try:
            with open(path, "r", errors="ignore") as f:
                f.seek(self._pos)
                chunk = f.read()
                self._pos = f.tell()
        except OSError:
            return

        for line in chunk.splitlines():
            if not line.strip():
                continue
            if self._cols is None:
                self._cols = self._parse_header(line)
                continue
            parts = line.split(",")
            row = {}
            for name, idx in self._cols.items():
                if idx < len(parts):
                    try:
                        row[name] = float(parts[idx])
                    except ValueError:
                        pass
            if "fps" not in row:
                continue

            # Horodatage : 'elapsed' est en nanosecondes chez MangoHud.
            # Sans cette colonne, on retombe sur le nombre d'échantillons.
            if "elapsed" in row:
                if self._t0 is None:
                    self._t0 = row["elapsed"]
                t = (row["elapsed"] - self._t0) / 1e9
            else:
                t = self._n * (LOG_INTERVAL_MS / 1000.0)
            self._n += 1

            # MangoHud écrit des images à 0 fps au lancement, et le tout
            # début de session est du chargement : on écarte les deux.
            if row["fps"] <= 0 or t < GAME_WARMUP_S:
                continue
            # Jeu suspendu (alt-tab / pause) : ce n'est pas de la performance.
            if row["fps"] < 1000.0 / FREEZE_IGNORE_MS:
                continue

            self._samples.append((t, row["fps"], row.get("frametime")))
            self._last = row

    # -- API -------------------------------------------------------------- #
    def sample(self):
        """Renvoie un dict décrivant la session, ou None si aucun jeu actif."""
        path, mtime = self._newest_log()
        if not path:
            return None
        if path != self._path:
            self._reset_for(path)
        self._consume(path)

        live = (time.time() - mtime) <= FPS_STALE_SECONDS
        return game_stats(
            list(self._samples), live, self._game_name(path),
            extra={
                "cpu_load": self._last.get("cpu_load"),
                "gpu_load": self._last.get("gpu_load"),
                "vram_used": self._last.get("gpu_vram_used"),
            },
        )

    def stop(self):
        """Rien à arrêter : la lecture se fait dans le thread d'échantillonnage."""


class RtssGameReader:
    """Session de jeu sous Windows, mesurée sur la mémoire partagée de RivaTuner.

    RTSS tient, pour chaque application accrochée, un compteur d'images qui
    n'avance que quand elle dessine. On l'échantillonne toutes les WIN_POLL_MS
    dans un thread dédié — le thread principal, lui, ne tique qu'une fois par
    seconde, ce qui donnerait 60 points par minute et rendrait le 0.1% low
    dénué de sens.

    Choisir la bonne application est le point délicat : RTSS accroche aussi
    l'explorateur, les navigateurs et les launchers, qui affichent volontiers
    120 fps sur le bureau. Deux garde-fous :
      * Afterburner sert d'arbitre — son capteur « Framerate » n'est actif que
        lorsqu'un jeu tourne réellement ;
      * à défaut, on suit la fenêtre au premier plan.
    """

    SIGNATURES = (0x53535452, 0x52545353)   # RTSS < 7, puis RTSS 7.x

    @staticmethod
    def _afterburner_fps():
        """FPS publié par Afterburner, ou None si aucun jeu ne tourne.

        Hors jeu, le capteur ne vaut pas toujours FLT_MAX : Afterburner le
        remet aussi à 0 selon le moment. Les deux cas signifient « pas de jeu ».
        """
        fps = AB.get("Framerate")
        return fps if fps is not None and 1.0 < fps < 1000.0 else None

    def __init__(self):
        self._samples = deque(maxlen=GAME_HISTORY)
        self._pid = None          # application suivie
        self._name = None
        self._t0 = None           # instant de départ de la session
        self._prev = None         # (compteur d'images, instant) du tour précédent
        self._last_seen = 0.0     # dernière image effectivement comptée
        self._poller = None

    # -- collecte (thread dédié) ------------------------------------------ #
    def start(self):
        if IS_WINDOWS and self._poller is None:
            self._poller = _GamePoller(self)
            self._poller.start()

    def stop(self):
        if self._poller is not None:
            self._poller.stop()
            self._poller = None

    def _entries(self, data, header):
        """Itère les applications accrochées : (pid, nom_exe, compteur_images)."""
        import struct
        sig, _ver, entry_sz, arr_off, arr_cnt = struct.unpack_from("<IIIII", header, 0)

        # RTSS 7.x a déplacé les champs de l'entrée (structure confirmée par
        # analyse différentielle de la mémoire pendant une partie).
        if sig == 0x52545353:
            pid_off, name_off, fc_off, min_size = 0, 4, 296, 300
        else:
            pid_off, name_off, fc_off, min_size = 4, 12, 272, 280

        for i in range(arr_cnt):
            base = arr_off + i * entry_sz
            if base + min_size > len(data):
                return
            pid = struct.unpack_from("<I", data, base + pid_off)[0]
            if pid == 0:
                continue
            path = data[base + name_off:base + name_off + 260].split(b"\0")[0]
            frames = struct.unpack_from("<I", data, base + fc_off)[0]
            yield pid, path.decode("latin-1", "ignore"), frames

    def _read_entries(self):
        import struct
        captured = {}

        def total_size(header):
            sig, _ver, entry_sz, arr_off, arr_cnt = struct.unpack_from("<IIIII", header, 0)
            if sig not in self.SIGNATURES or entry_sz == 0 or arr_cnt == 0:
                return None
            # Garde-fous contre un en-tête corrompu (RTSS 7.x occupe ~5,3 Mo).
            if entry_sz > 131072 or arr_cnt > 1024 or arr_off > 64 * 1024 * 1024:
                return None
            total = arr_off + arr_cnt * entry_sz
            if total > 64 * 1024 * 1024:
                return None
            captured["header"] = header
            return total

        data = _read_shared_memory(RTSS_SHARED_MEMORY, total_size)
        if not data or "header" not in captured:
            return []
        try:
            return list(self._entries(data, captured["header"]))
        except Exception:
            return []

    @staticmethod
    def _foreground_pid():
        """PID de la fenêtre active (0 si indéterminé)."""
        try:
            import ctypes
            u32 = ctypes.windll.user32
            u32.GetForegroundWindow.restype = ctypes.c_void_p
            hwnd = u32.GetForegroundWindow()
            if not hwnd:
                return 0
            pid = ctypes.c_uint32(0)
            u32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
            return pid.value
        except Exception:
            return 0

    @staticmethod
    def _game_name(path):
        """'D:\\...\\RDR2.exe' -> 'Rdr2'"""
        base = os.path.basename(path.replace("\\", "/"))
        base = re.sub(r"\.exe$", "", base, flags=re.I)
        return base.replace("_", " ").strip().title() or tr("Game")

    def _pick(self, entries):
        """Entrée correspondant au jeu, ou None."""
        if not entries:
            return None
        # Afterburner ne publie un « Framerate » exploitable que lorsqu'un jeu
        # tourne : sans ce signal, tout ce que RTSS accroche n'est que du bureau
        # (le dock, le navigateur… qui tournent volontiers à 120 fps).
        if AB.available() and self._afterburner_fps() is None:
            return None

        by_pid = {pid: (pid, name, frames) for pid, name, frames in entries}

        if self._pid in by_pid:          # on reste sur le jeu déjà suivi
            return by_pid[self._pid]
        foreground = self._foreground_pid()
        if foreground in by_pid:
            return by_pid[foreground]
        return None

    def poll(self):
        """Un relevé. Appelé toutes les WIN_POLL_MS par le thread dédié."""
        entry = self._pick(self._read_entries())
        now = time.monotonic()
        if entry is None:
            self._prev = None       # le delta d'après serait faussé par la coupure
            return

        pid, path, frames = entry
        if pid != self._pid:        # nouveau jeu : on repart de zéro
            self._samples.clear()
            self._pid = pid
            self._name = self._game_name(path)
            self._t0 = now
            self._prev = None

        prev = self._prev
        self._prev = (frames, now)
        if prev is None:
            return
        prev_frames, prev_t = prev
        dt = now - prev_t
        df = frames - prev_frames
        if not (0.02 < dt < 5.0) or df <= 0:
            return

        fps = df / dt
        if not 1.0 < fps < 1000.0:
            return
        t = now - self._t0
        # Mêmes exclusions que sous Linux : le tout début de session est du
        # chargement, et une image de plus d'une seconde est un jeu suspendu.
        if t < GAME_WARMUP_S or fps < 1000.0 / FREEZE_IGNORE_MS:
            return
        # Le frametime est déduit du débit d'images sur la fenêtre de 100 ms :
        # RTSS ne publie pas la durée image par image, donc les pics les plus
        # brefs sont lissés — c'est la limite de cette source face à MangoHud.
        self._samples.append((t, fps, 1000.0 / fps))
        self._last_seen = now

    # -- API -------------------------------------------------------------- #
    def sample(self):
        if not self._samples:
            return None
        live = (time.monotonic() - self._last_seen) <= FPS_STALE_SECONDS
        # Le FPS montré est celui d'Afterburner quand il est disponible : c'est
        # le chiffre que RivaTuner affiche en jeu, à l'identique.
        extra = {}
        shown = self._afterburner_fps()
        if live and shown is not None:
            extra["fps"] = shown
        return game_stats(list(self._samples), live, self._name, extra=extra)


class _GamePoller(QThread):
    """Thread de relevé haute fréquence du lecteur de jeu Windows."""

    def __init__(self, reader):
        super().__init__()
        self._reader = reader
        self._running = True

    def run(self):
        while self._running:
            try:
                self._reader.poll()
            except Exception:
                pass        # un relevé raté ne doit pas tuer le thread
            self.msleep(WIN_POLL_MS)

    def stop(self):
        self._running = False
        self.wait(2000)


def make_game_reader():
    """Lecteur de session adapté à la plateforme."""
    return RtssGameReader() if IS_WINDOWS else MangoHudGameReader()


def bottleneck(cpu_load, gpu_load):
    """Devine ce qui limite les FPS. Renvoie (texte, rôle de couleur)."""
    if cpu_load is None or gpu_load is None:
        return None, None
    if gpu_load >= 95:
        return tr("GPU maxed out — GPU-bound"), "gpu"
    if cpu_load >= 85 and gpu_load < 90:
        return tr("CPU maxed out — CPU-bound"), "cpu"
    if gpu_load < 80 and cpu_load < 80:
        return tr("Neither CPU nor GPU saturated — limited by FPS cap / vsync"), "muted"
    return tr("Balanced load"), "muted"


# ----------------------------------------------------------------------------- #
#  Thread d'échantillonnage (évite de bloquer l'UI avec nvidia-smi)
# ----------------------------------------------------------------------------- #

class Sampler(QThread):
    sampled = Signal(dict)

    def __init__(self):
        super().__init__()
        self._running = True
        self.interval_ms = DEFAULT_INTERVAL_MS
        self._cpu = CpuReader()
        self._game = make_game_reader()

    def run(self):
        if hasattr(self._game, "start"):
            self._game.start()
        while self._running:
            data = {}
            data.update(self._cpu.sample())
            data.update(read_ram())
            data.update(read_gpu())

            game = self._game.sample()
            if game is not None:
                # MangoHud consigne les charges CPU/GPU ligne par ligne ; RTSS
                # non. Dans les deux cas, les mesures système du tour en cours
                # font l'affaire pour situer le goulot d'étranglement.
                if game.get("cpu_load") is None:
                    game["cpu_load"] = data.get("cpu_pct")
                if game.get("gpu_load") is None:
                    game["gpu_load"] = data.get("gpu_pct")
            data["game"] = game

            self.sampled.emit(data)
            # sommeil découpé pour réagir vite à l'arrêt / changement d'intervalle
            slept = 0
            while self._running and slept < self.interval_ms:
                self.msleep(50)
                slept += 50

    def stop(self):
        self._running = False
        self._game.stop()
        self.wait(2000)


# ----------------------------------------------------------------------------- #
#  Widgets graphiques
# ----------------------------------------------------------------------------- #

class Sparkline(QWidget):
    """Courbe d'historique remplie. max_value=None => échelle auto."""

    def __init__(self, role, max_value=100.0):
        super().__init__()
        self.role = role
        self.max_value = max_value
        self.data = deque(maxlen=HISTORY)
        self.setMinimumHeight(54)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def push(self, value):
        self.data.append(value)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        color = QColor(col(self.role))

        if not self.data:
            return
        vals = list(self.data)
        valid = [v for v in vals if v is not None]
        if not valid:
            return

        if self.max_value is not None:
            vmax = self.max_value
        else:
            vmax = max(valid) * 1.15 or 1.0

        n = len(vals)
        step = w / max(1, n - 1)

        def pt(i, v):
            return QPointF(i * step, h - (min(v, vmax) / vmax) * (h - 4) - 2)

        # On découpe en segments contigus (sauts sur les None).
        line = QPen(color, 2)
        line.setJoinStyle(Qt.RoundJoin)
        i = 0
        while i < n:
            if vals[i] is None:
                i += 1
                continue
            j = i
            seg = []
            while j < n and vals[j] is not None:
                seg.append((j, vals[j]))
                j += 1
            if len(seg) >= 1:
                path = QPainterPath()
                path.moveTo(pt(seg[0][0], seg[0][1]))
                for k, v in seg[1:]:
                    path.lineTo(pt(k, v))
                # remplissage dégradé sous la courbe
                fill = QPainterPath(path)
                fill.lineTo(QPointF(seg[-1][0] * step, h))
                fill.lineTo(QPointF(seg[0][0] * step, h))
                fill.closeSubpath()
                grad = QLinearGradient(0, 0, 0, h)
                c = QColor(color)
                c.setAlpha(90)
                grad.setColorAt(0, c)
                c2 = QColor(color)
                c2.setAlpha(0)
                grad.setColorAt(1, c2)
                p.fillPath(fill, QBrush(grad))
                p.strokePath(path, line)
            i = j


class FrametimeGraph(QWidget):
    """Graphe des frametimes (ms). Les pics = micro-saccades ressenties en jeu.

    Une ligne de repère est tracée à la cible (ex. 6,06 ms pour 165 fps) :
    tout ce qui dépasse nettement se voit immédiatement.
    """

    def __init__(self, role="ft"):
        super().__init__()
        self.role = role
        self.data = []
        self.target_ms = 1000.0 / DEFAULT_FPS_TARGET
        self.setMinimumHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, values, target_ms=None):
        # On n'affiche que la fin de la session (le graphe défile).
        self.data = list(values)[-HISTORY:]
        if target_ms:
            self.target_ms = target_ms
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        color = QColor(col(self.role))
        muted = QColor(col("muted"))

        if len(self.data) < 2:
            p.setPen(muted)
            p.drawText(self.rect(), Qt.AlignCenter, tr("waiting for data…"))
            return

        # Échelle : au moins 2x la cible, sinon le pic max (avec marge).
        peak = max(self.data)
        top = max(self.target_ms * 2.0, peak * 1.15)

        def y_of(v):
            return h - (min(v, top) / top) * h

        # Ligne de repère (cible)
        ty = y_of(self.target_ms)
        pen = QPen(muted, 1, Qt.DashLine)
        p.setPen(pen)
        p.drawLine(0, int(ty), w, int(ty))
        p.setPen(muted)
        f = p.font(); f.setPointSize(8); p.setFont(f)
        p.drawText(4, max(10, int(ty) - 3), f"{self.target_ms:.1f} ms")

        # Courbe remplie
        step = w / max(1, len(self.data) - 1)
        path = QPainterPath()
        path.moveTo(0, y_of(self.data[0]))
        for i, v in enumerate(self.data[1:], start=1):
            path.lineTo(i * step, y_of(v))

        fill = QPainterPath(path)
        fill.lineTo(w, h)
        fill.lineTo(0, h)
        fill.closeSubpath()
        grad = QLinearGradient(0, 0, 0, h)
        c = QColor(color); c.setAlpha(110)
        grad.setColorAt(0, c)
        c2 = QColor(color); c2.setAlpha(10)
        grad.setColorAt(1, c2)
        p.fillPath(fill, QBrush(grad))

        p.setPen(QPen(color, 1.6))
        p.drawPath(path)

        # Marqueurs sur les pics importants (> 2x la cible)
        spike = self.target_ms * 2.0
        bad = QColor(col("bad"))
        p.setPen(QPen(bad, 1))
        p.setBrush(QBrush(bad))
        for i, v in enumerate(self.data):
            if v >= spike:
                p.drawEllipse(QPointF(i * step, y_of(v)), 2.2, 2.2)


class CircularGauge(QWidget):
    """Jauge circulaire : anneau de progression + valeur au centre."""

    def __init__(self, role):
        super().__init__()
        self.role = role
        self.percent = 0.0
        self.big = "—"
        self.sub = ""
        self.sub_role = "muted"
        self.setMinimumSize(150, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set(self, percent, big, sub, sub_role=None):
        self.percent = max(0.0, min(100.0, percent))
        self.big = big
        self.sub = sub
        self.sub_role = sub_role or "muted"
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        side = min(w, h)
        thick = max(8, side * 0.11)
        margin = thick / 2 + 4
        rect = QRectF(
            (w - side) / 2 + margin,
            (h - side) / 2 + margin,
            side - 2 * margin,
            side - 2 * margin,
        )

        # anneau de fond
        bg = QPen(QColor(col("ring")), thick)
        bg.setCapStyle(Qt.RoundCap)
        p.setPen(bg)
        p.drawArc(rect, 0, 360 * 16)

        # arc de progression (départ en haut, sens horaire)
        pen = QPen(QColor(col(self.role)), thick)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        span = int(-self.percent / 100.0 * 360 * 16)
        p.drawArc(rect, 90 * 16, span)

        # valeur centrale
        p.setPen(QColor(col("text")))
        f = QFont()
        f.setPointSizeF(max(14, side * 0.16))
        f.setBold(True)
        p.setFont(f)
        big_rect = QRectF(rect.x(), rect.y(), rect.width(), rect.height() * 0.70)
        p.drawText(big_rect, Qt.AlignCenter, self.big)

        # sous-texte (peut contenir plusieurs lignes via \n)
        p.setPen(QColor(col(self.sub_role)))
        sf = QFont()
        sf.setPointSizeF(max(8, side * 0.058))
        p.setFont(sf)
        sub_rect = QRectF(
            rect.x(), rect.y() + rect.height() * 0.54,
            rect.width(), rect.height() * 0.34,
        )
        p.drawText(sub_rect, Qt.AlignHCenter | Qt.AlignTop, self.sub)


class GaugeCard(QFrame):
    """Carte contenant un titre et une jauge circulaire."""

    def __init__(self, title, role):
        super().__init__()
        self.setObjectName("card")
        self.role = role
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(4)

        top = QHBoxLayout()
        self.dot = QLabel("●")
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        top.addWidget(self.dot)
        top.addWidget(self.title)
        top.addStretch()
        lay.addLayout(top)

        # Nom du matériel détecté (CPU/GPU/RAM…) sous le titre
        self.hw = QLabel("")
        self.hw.setObjectName("cardHw")
        lay.addWidget(self.hw)

        self.gauge = CircularGauge(role)
        lay.addWidget(self.gauge, 1)

        # Courbe de tendance : montre les pics des dernières minutes,
        # que la jauge instantanée ne peut pas révéler.
        self.trend = Sparkline(role, max_value=100.0)
        self.trend.setMinimumHeight(28)
        self.trend.setMaximumHeight(34)
        lay.addWidget(self.trend)

        self.retheme()

    def update_value(self, percent, big, sub, sub_role=None):
        """Met à jour la jauge ET la courbe de tendance d'un coup."""
        self.gauge.set(percent, big, sub, sub_role)
        self.trend.push(percent)

    def retheme(self):
        """Réapplique les couleurs posées en ligne (le QSS global ne les couvre pas)."""
        self.dot.setStyleSheet(f"color:{col(self.role)}; font-size:12px;")
        self.hw.setStyleSheet(f"color:{col(self.role)};")
        self.gauge.update()
        self.trend.update()


class StatBox(QVBoxLayout):
    """Petite statistique : grande valeur + libellé dessous."""

    def __init__(self, label, role="text", big=False):
        super().__init__()
        self.setSpacing(0)
        self._font_px = 34 if big else 20
        self.role = role
        self.value = QLabel("—")
        self.retheme()
        self.value.setAlignment(Qt.AlignCenter)
        self.cap = QLabel(label)
        self.cap.setObjectName("cardSub")
        self.cap.setAlignment(Qt.AlignCenter)
        self.addWidget(self.value)
        self.addWidget(self.cap)

    def set(self, text, role=None):
        self.value.setText(text)
        if role and role != self.role:
            self.role = role
            self.retheme()

    def retheme(self):
        self.value.setStyleSheet(
            f"color:{col(self.role)}; font-size:{self._font_px}px; font-weight:700;"
        )


class GamePanel(QFrame):
    """Panneau gaming : FPS, 1% low, 0.1% low, frametime et goulot d'étranglement.

    Le 1% low est ce qui se ressent vraiment en jeu : une moyenne de 120 fps
    avec un 1% low à 40 donne une expérience saccadée.
    """

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        # En-tête : titre + nom du jeu détecté
        top = QHBoxLayout()
        self.dot = QLabel("●")
        self.title = QLabel(tr("IN GAME"))
        self.title.setObjectName("cardTitle")
        top.addWidget(self.dot)
        top.addWidget(self.title)
        top.addStretch()
        self.game = QLabel("")
        self.game.setObjectName("cardHw")
        top.addWidget(self.game)
        lay.addLayout(top)

        # Ligne de statistiques
        stats = QHBoxLayout()
        stats.setSpacing(6)
        self.s_fps = StatBox("FPS", "fps", big=True)
        self.s_low1 = StatBox(tr("1% LOW ({win:.0f} s)").format(win=GAME_WINDOW_S), "text")
        self.s_low01 = StatBox(tr("0.1% LOW ({win:.0f} s)").format(win=GAME_WINDOW_S), "text")
        self.s_avg = StatBox(tr("AVERAGE ({win:.0f} s)").format(win=GAME_WINDOW_S), "muted")
        self.s_ft = StatBox("FRAMETIME", "ft")
        for s in (self.s_fps, self.s_low1, self.s_low01, self.s_avg, self.s_ft):
            stats.addLayout(s)
        lay.addLayout(stats)

        # Goulot d'étranglement
        self.bottle = QLabel("")
        self.bottle.setObjectName("cardSub")
        self.bottle.setAlignment(Qt.AlignCenter)
        self.bottle_role = "muted"
        lay.addWidget(self.bottle)

        # Graphe de frametime
        self.ft_graph = FrametimeGraph()
        lay.addWidget(self.ft_graph, 1)

        self.status = QLabel(no_game_text())
        self.status.setObjectName("cardSub")
        self.status.setAlignment(Qt.AlignCenter)
        self.idle = True     # aucun jeu détecté : le statut est un texte fixe
        lay.addWidget(self.status)

        self.retheme()

    def retext(self):
        """Repose les libellés fixes après un changement de langue. Le reste
        (statut, goulot, valeurs) est réécrit au prochain échantillon."""
        self.title.setText(tr("IN GAME"))
        for box, key in (
            (self.s_low1, "1% LOW ({win:.0f} s)"),
            (self.s_low01, "0.1% LOW ({win:.0f} s)"),
            (self.s_avg, "AVERAGE ({win:.0f} s)"),
        ):
            box.cap.setText(tr(key).format(win=GAME_WINDOW_S))
        if self.idle:
            self.status.setText(no_game_text())

    def retheme(self):
        self.dot.setStyleSheet(f"color:{col('fps')}; font-size:12px;")
        self.game.setStyleSheet(f"color:{col('fps')};")
        for s in (self.s_fps, self.s_low1, self.s_low01, self.s_avg, self.s_ft):
            s.retheme()
        self._apply_bottle()
        self.ft_graph.update()

    def _apply_bottle(self):
        self.bottle.setStyleSheet(
            f"color:{col(self.bottle_role)}; font-size:12px; font-weight:600;"
        )

    def _fps_role(self, v, target):
        if v is None:
            return "muted"
        if v >= target * 0.85:
            return "ok"
        if v >= target * 0.5:
            return "warn"
        return "bad"

    def clear(self):
        for s in (self.s_fps, self.s_low1, self.s_low01, self.s_avg, self.s_ft):
            s.value.setText("—")
        self.game.setText("")
        self.bottle.setText("")
        self.ft_graph.set_data([])
        self.idle = True
        self.status.setText(no_game_text())

    def update_game(self, g, target):
        self.idle = False
        self.game.setText(g["name"])

        if g["live"] and g["fps"] is not None:
            self.s_fps.set(f"{g['fps']:.0f}", self._fps_role(g["fps"], target))
        else:
            self.s_fps.set("—", "muted")

        self.s_low1.set(f"{g['low1']:.0f}", self._fps_role(g["low1"], target))
        self.s_low01.set(f"{g['low01']:.0f}", self._fps_role(g["low01"], target))
        self.s_avg.set(f"{g['avg']:.0f}")

        ft = g["frametime"]
        self.s_ft.set(f"{ft:.1f} ms" if ft else "—")

        txt, role = bottleneck(g["cpu_load"], g["gpu_load"])
        self.bottle.setText(txt or "")
        if txt:
            self.bottle_role = role
            self._apply_bottle()

        self.ft_graph.set_data(g["ft_history"], target_ms=1000.0 / target)

        state = tr("Session running") if g["live"] else tr("Last session (ended)")
        self.status.setText(
            tr("{state} · {mins:.1f} min played · lows over the last {win:.0f} s "
               "· session range {low:.0f}–{high:.0f} fps").format(
                state=state, mins=g["duration_s"] / 60, win=g["window_s"],
                low=g["min"], high=g["max"],
            )
        )


# ----------------------------------------------------------------------------- #
#  Menu déroulant
# ----------------------------------------------------------------------------- #

class DropDownComboBox(QComboBox):
    """Liste déroulante qui s'ouvre TOUJOURS sous le champ, sur un fond opaque.

    Laissés au style du bureau, Breeze et Adwaita affichent la liste comme un
    menu centré sur l'entrée courante : choisie la dernière entrée, la liste
    s'ouvre vers le haut — déroutant — et son fond translucide laisse voir le
    bureau à travers. La règle QSS « combobox-popup: 0 » impose la liste
    déroulante classique ; les deux réglages ci-dessous rendent son conteneur
    opaque. Ils sont reposés à chaque ouverture car le style du bureau les
    réapplique après coup (et seule une fenêtre encore invisible peut changer
    de transparence).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setView(QListView())

    def showPopup(self):
        popup = self.view().window()
        popup.setAttribute(Qt.WA_TranslucentBackground, False)
        popup.setAutoFillBackground(True)
        super().showPopup()


# ----------------------------------------------------------------------------- #
#  Fenêtre principale
# ----------------------------------------------------------------------------- #

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CachyMonitor")
        self.resize(560, 720)
        self.theme_mode = DEFAULT_THEME
        self.lang_mode = DEFAULT_LANG

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        # En-tête : titre + bouton qui déplie les réglages
        header = QHBoxLayout()
        title = QLabel("CachyMonitor")
        title.setObjectName("appTitle")
        header.addWidget(title)
        header.addStretch()

        self.opt_button = QToolButton()
        self.opt_button.setObjectName("optButton")
        self.opt_button.setText("⚙  Options")
        self.opt_button.setCheckable(True)
        self.opt_button.setCursor(Qt.PointingHandCursor)
        header.addWidget(self.opt_button)
        root.addLayout(header)

        # Le panneau existe avant qu'on branche le signal : _toggle_options
        # planterait s'il se déclenchait sur un self.options pas encore créé.
        self._build_options()
        root.addWidget(self.options)
        self.opt_button.toggled.connect(self._toggle_options)

        # Cartes
        grid = QGridLayout()
        grid.setSpacing(14)

        self.cpu = GaugeCard("CPU", "cpu")
        self.gpu = GaugeCard("GPU", "gpu")
        self.ram = GaugeCard("RAM", "ram")
        self.vram = GaugeCard("VRAM", "vram")
        self.game = GamePanel()

        grid.addWidget(self.cpu, 0, 0)
        grid.addWidget(self.gpu, 0, 1)
        grid.addWidget(self.ram, 1, 0)
        grid.addWidget(self.vram, 1, 1)
        grid.addWidget(self.game, 2, 0, 1, 2)
        grid.setRowStretch(2, 1)
        root.addLayout(grid, 1)

        # Noms matériel statiques (lus une seule fois)
        self.cpu.hw.setText(read_cpu_name())
        self.ram.hw.setText(read_ram_name())

        self.status = QLabel(tr("Starting…"))
        self.started = False   # passe à True au 1er échantillon (statut réel)
        self.status.setObjectName("status")
        root.addWidget(self.status)

        # Réglages mémorisés (intervalle, cible FPS, thème, langue, "au-dessus",
        # géométrie). Les textes sont posés avec la langue par défaut pendant la
        # construction : retext() les repose dans celle qui a été mémorisée.
        self._load_settings()
        self.retext()
        self.apply_theme()

        # Suivi du thème du bureau quand le mode « Système » est choisi.
        QApplication.instance().styleHints().colorSchemeChanged.connect(
            self._on_system_theme_changed
        )

        # Sampler
        self.sampler = Sampler()
        self.sampler.interval_ms = self.interval.value()
        self.sampler.sampled.connect(self.on_sample)
        self.sampler.start()

    # -- panneau Options ---------------------------------------------------- #
    def _build_options(self):
        """Zone de réglages dépliable. Repliée par défaut : l'écran reste dédié
        aux mesures, qui sont la raison d'être de l'application."""
        self.options = QFrame()
        self.options.setObjectName("options")
        self.options.setVisible(False)

        grid = QGridLayout(self.options)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self.interval = QSpinBox()
        self.interval.setRange(200, 5000)
        self.interval.setSingleStep(100)
        self.interval.setValue(DEFAULT_INTERVAL_MS)
        self.interval.setSuffix(" ms")
        self.interval.setToolTip(tr("Measurement refresh rate"))
        self.interval.valueChanged.connect(self._set_interval)

        self.fps_target = QSpinBox()
        self.fps_target.setRange(30, 500)
        self.fps_target.setSingleStep(5)
        self.fps_target.setValue(DEFAULT_FPS_TARGET)
        self.fps_target.setToolTip(
            tr("Scales the FPS colours and marks the frametime graph")
        )

        self.theme = DropDownComboBox()
        for mode in THEME_MODES:
            self.theme.addItem(tr(THEME_LABELS[mode]), mode)
        self.theme.setToolTip(tr("« System » follows the desktop light/dark setting"))
        self.theme.currentIndexChanged.connect(self._set_theme)

        self.lang = DropDownComboBox()
        for mode in LANG_MODES:
            self.lang.addItem(tr(LANG_LABELS[mode]), mode)
        self.lang.setToolTip(tr("« System » follows the desktop language"))
        self.lang.currentIndexChanged.connect(self._set_language)

        self.ontop = QCheckBox(tr("Always on top"))
        self.ontop.toggled.connect(self._toggle_ontop)

        self.l_interval = QLabel(tr("Interval"))
        self.l_fps = QLabel(tr("FPS target"))
        self.l_theme = QLabel(tr("Theme"))
        self.l_lang = QLabel(tr("Language"))

        grid.addWidget(self.l_interval, 0, 0)
        grid.addWidget(self.interval, 0, 1)
        grid.addWidget(self.l_fps, 0, 2)
        grid.addWidget(self.fps_target, 0, 3)
        grid.addWidget(self.l_theme, 1, 0)
        grid.addWidget(self.theme, 1, 1)
        grid.addWidget(self.l_lang, 1, 2)
        grid.addWidget(self.lang, 1, 3)
        grid.addWidget(self.ontop, 2, 0, 1, 4)
        grid.setColumnStretch(4, 1)

    def _toggle_options(self, shown):
        self.options.setVisible(shown)

    # -- langue ------------------------------------------------------------- #
    def _set_language(self, _index):
        self.lang_mode = self.lang.currentData()
        set_language(self.lang_mode)
        self.retext()

    def retext(self):
        """Repose tous les textes fixes de l'interface dans la langue active.

        Les textes qui dépendent des mesures (statut, goulot, unités des jauges)
        ne sont pas touchés ici : ils sont réécrits au prochain échantillon, donc
        au plus tard après un intervalle de rafraîchissement.
        """
        self.interval.setToolTip(tr("Measurement refresh rate"))
        self.fps_target.setToolTip(
            tr("Scales the FPS colours and marks the frametime graph")
        )
        self.l_interval.setText(tr("Interval"))
        self.l_fps.setText(tr("FPS target"))
        self.l_theme.setText(tr("Theme"))
        self.l_lang.setText(tr("Language"))
        self.ontop.setText(tr("Always on top"))
        self.theme.setToolTip(tr("« System » follows the desktop light/dark setting"))
        self.lang.setToolTip(tr("« System » follows the desktop language"))

        # Les entrées des listes : on réécrit le libellé sans toucher au choix.
        for combo, labels in ((self.theme, THEME_LABELS), (self.lang, LANG_LABELS)):
            for i in range(combo.count()):
                combo.setItemText(i, tr(labels[combo.itemData(i)]))

        self.game.retext()
        # Capacité RAM : lue une seule fois au démarrage, son unité est traduite.
        self.ram.hw.setText(read_ram_name())
        if not self.started:
            self.status.setText(tr("Starting…"))

    # -- thème -------------------------------------------------------------- #
    def _set_theme(self, _index):
        self.theme_mode = self.theme.currentData()
        self.apply_theme()

    def _on_system_theme_changed(self, _scheme):
        """Le bureau est passé du clair au sombre (ou l'inverse)."""
        if self.theme_mode == "systeme":
            self.apply_theme()

    def apply_theme(self):
        """Bascule la palette et redessine tout, sans redémarrer l'application :
        l'historique des courbes et la session de jeu en cours sont conservés."""
        set_palette(resolve_theme(self.theme_mode))
        app = QApplication.instance()
        app.setPalette(build_palette())
        app.setStyleSheet(build_style())
        # Le QSS ne couvre pas les couleurs posées en ligne ni le QPainter.
        for card in (self.cpu, self.gpu, self.ram, self.vram, self.game):
            card.retheme()
        self.update()

    # -- handlers ----------------------------------------------------------- #
    def _set_interval(self, v):
        self.sampler.interval_ms = v

    def _toggle_ontop(self, on):
        flag = Qt.WindowStaysOnTopHint
        self.setWindowFlag(flag, on)
        self.show()

    def on_sample(self, d):
        # CPU
        t = d["cpu_temp"]
        freq = f"{d['cpu_freq']/1000:.2f} GHz" if d["cpu_freq"] else "—"
        ttxt = f"{t:.0f}°C" if t is not None else "—"
        power = d.get("cpu_power")
        line = f"{freq} · {power:.0f} W" if power else freq
        self.cpu.update_value(d["cpu_pct"], f"{d['cpu_pct']:.0f}%",
                              f"{line}\n{ttxt}", temp_role(t))

        # GPU
        gpu_name = d["gpu_name"].replace("NVIDIA ", "")
        if self.gpu.hw.text() != gpu_name:
            self.gpu.hw.setText(gpu_name)
            self.vram.hw.setText(gpu_name)
        gt = d["gpu_temp"]
        gttxt = f"{gt:.0f}°C" if gt is not None else "—"
        pw = f"{d['gpu_power']:.0f} W" if d["gpu_power"] else "—"
        self.gpu.update_value(d["gpu_pct"], f"{d['gpu_pct']:.0f}%",
                              f"{pw}\n{gttxt}", temp_role(gt))

        # RAM
        self.ram.update_value(d["ram_pct"], f"{d['ram_pct']:.0f}%",
                              f"{d['ram_used']:.1f} / {d['ram_total']:.1f} {tr('GiB')}")

        # VRAM
        vt, vu = d["vram_total"], d["vram_used"]
        vpct = (vu / vt * 100) if vt else 0
        self.vram.update_value(vpct, f"{vpct:.0f}%",
                               f"{vu/1024:.1f} / {vt/1024:.1f} {tr('GiB')}")

        # Session de jeu (MangoHud)
        g = d.get("game")
        if g is None:
            self.game.clear()
        else:
            self.game.update_game(g, self.fps_target.value())

        self.started = True
        self.status.setText(
            tr("Updated every {ms} ms").format(ms=self.sampler.interval_ms)
            + f" · {time.strftime('%H:%M:%S')}"
        )

    # -- persistance des réglages ------------------------------------------- #
    def _load_settings(self):
        """Restaure les réglages. Appelé AVANT la création du sampler : on coupe
        les signaux pendant la restauration, sinon _set_interval s'exécuterait
        alors que self.sampler n'existe pas encore."""
        s = QSettings("CachyMonitor", "CachyMonitor")

        for widget, key, default in (
            (self.interval, "interval_ms", DEFAULT_INTERVAL_MS),
            (self.fps_target, "fps_target", DEFAULT_FPS_TARGET),
        ):
            try:
                value = int(s.value(key, default))
            except (TypeError, ValueError):
                value = default
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)

        # Thème : le mode est appliqué juste après, par apply_theme().
        mode = s.value("theme", DEFAULT_THEME)
        if mode not in THEME_MODES:
            mode = DEFAULT_THEME
        self.theme_mode = mode
        self.theme.blockSignals(True)
        self.theme.setCurrentIndex(THEME_MODES.index(mode))
        self.theme.blockSignals(False)

        # Langue : les textes sont reposés juste après, par retext().
        lang = s.value("language", DEFAULT_LANG)
        if lang not in LANG_MODES:
            lang = DEFAULT_LANG
        self.lang_mode = lang
        set_language(lang)
        self.lang.blockSignals(True)
        self.lang.setCurrentIndex(LANG_MODES.index(lang))
        self.lang.blockSignals(False)

        # QSettings renvoie les booléens en texte selon le backend.
        if _as_bool(s.value("options_open", False)):
            self.opt_button.setChecked(True)

        ontop = _as_bool(s.value("ontop", False))
        if ontop:
            self.ontop.blockSignals(True)
            self.ontop.setChecked(True)
            self.ontop.blockSignals(False)
            # On applique le drapeau sans appeler show() (la fenêtre n'est pas
            # encore affichée à ce stade).
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        geo = s.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)

    def _save_settings(self):
        s = QSettings("CachyMonitor", "CachyMonitor")
        s.setValue("interval_ms", self.interval.value())
        s.setValue("fps_target", self.fps_target.value())
        s.setValue("theme", self.theme_mode)
        s.setValue("language", self.lang_mode)
        s.setValue("options_open", self.opt_button.isChecked())
        s.setValue("ontop", self.ontop.isChecked())
        s.setValue("geometry", self.saveGeometry())

    def closeEvent(self, e):
        self._save_settings()
        self.sampler.stop()
        super().closeEvent(e)


def build_palette():
    """Palette Qt du thème actif.

    Indispensable : les éléments dessinés par le style du bureau (flèches des
    compteurs, coche des cases, flèche du menu déroulant) ignorent la feuille de
    style et suivent la palette. Sans ça, un bureau en thème sombre les dessine
    en clair — donc invisibles — dès qu'on passe CachyMonitor en thème clair.
    """
    pal = QPalette()
    bg, card = QColor(col("bg")), QColor(col("card"))
    text, muted = QColor(col("text")), QColor(col("muted"))
    for role, c in (
        (QPalette.Window, bg),
        (QPalette.WindowText, text),
        (QPalette.Base, card),
        (QPalette.AlternateBase, bg),
        (QPalette.Text, text),
        (QPalette.Button, card),
        (QPalette.ButtonText, text),
        (QPalette.ToolTipBase, card),
        (QPalette.ToolTipText, text),
        (QPalette.PlaceholderText, muted),
        (QPalette.Highlight, QColor(col("cpu"))),
        (QPalette.HighlightedText, card),
    ):
        pal.setColor(role, c)
    pal.setColor(QPalette.Disabled, QPalette.Text, muted)
    pal.setColor(QPalette.Disabled, QPalette.WindowText, muted)
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, muted)
    return pal


def build_style():
    """Feuille de style du thème actif (regénérée à chaque changement)."""
    return f"""
QWidget {{ background: {col('bg')}; color: {col('text')}; font-family: 'Inter','Noto Sans',sans-serif; font-size: 13px; }}
/* Sans fond transparent, chaque libellé peint un rectangle de la couleur du
   fond général, visible comme une bande sur les cartes. */
QLabel, QCheckBox {{ background: transparent; }}
#appTitle {{ font-size: 20px; font-weight: 700; }}
#card {{ background: {col('card')}; border-radius: 14px; }}
#cardTitle {{ color: {col('muted')}; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }}
#cardHw {{ font-size: 11px; font-weight: 600; }}
#cardValue {{ font-size: 26px; font-weight: 700; }}
#cardSub {{ color: {col('muted')}; font-size: 12px; }}
#status {{ color: {col('muted')}; font-size: 11px; }}
#options {{ background: {col('card')}; border-radius: 12px; }}
#optButton {{ background: {col('card')}; color: {col('muted')}; border: 1px solid {col('border')}; border-radius: 8px; padding: 5px 12px; font-weight: 600; }}
#optButton:hover {{ color: {col('text')}; }}
#optButton:checked {{ color: {col('cpu')}; border-color: {col('cpu')}; }}
QSpinBox, QComboBox {{ background: {col('card')}; color: {col('text')}; border: 1px solid {col('border')}; border-radius: 6px; padding: 2px 6px; }}
/* combobox-popup: 0 => vraie liste déroulante sous le champ, au lieu du menu
   centré sur l'entrée courante que dessinent Breeze et Adwaita. */
QComboBox {{ combobox-popup: 0; }}
QComboBox QAbstractItemView {{ background-color: {col('card')}; color: {col('text')}; border: 1px solid {col('border')}; outline: 0; selection-background-color: {col('cpu')}; selection-color: {col('card')}; }}
/* Le conteneur du menu déroulant est translucide chez certains styles : on lui
   redonne un fond plein, sinon le bureau se voit à travers la liste. */
QComboBox QAbstractItemView::item {{ padding: 3px 6px; }}
QComboBox QListView {{ background-color: {col('card')}; }}
QCheckBox {{ color: {col('muted')}; spacing: 8px; }}
/* L'indicateur est dessiné ici plutôt que laissé au style natif : sous Windows,
   celui-ci suit le thème du SYSTÈME et non celui de l'application, si bien qu'un
   bureau en sombre dessinait une case blanche — invisible — dès que CachyMonitor
   passait en thème clair. Le remplissage plein signale l'état coché. */
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {col('border')}; border-radius: 4px; background: {col('bg')}; }}
QCheckBox::indicator:hover {{ border-color: {col('cpu')}; }}
QCheckBox::indicator:checked {{ background: {col('cpu')}; border-color: {col('cpu')}; }}
"""


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("CachyMonitor")
    # Windows n'affiche pas les SVG dans la barre des tâches : le .ico d'abord.
    here = asset_dir()
    names = ("cachymonitor.ico", "cachymonitor.svg") if IS_WINDOWS else \
            ("cachymonitor.svg", "cachymonitor.ico")
    for name in names:
        icon_path = os.path.join(here, name)
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            break
    else:
        app.setWindowIcon(QIcon.fromTheme("utilities-system-monitor"))
    # La palette de départ est posée par MainWindow (apply_theme), qui connaît
    # le mode mémorisé.
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
