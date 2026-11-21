"""CachyMonitor : module config (voir cachymonitor.py)."""

import os
import sys
import subprocess



# Dossier qui contient cachymonitor.py (et les icônes) : un cran au-dessus de ce paquet.
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Empêche l'apparition d'une fenêtre console à chaque subprocess.
_NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW}


# ----------------------------------------------------------------------------- #
#  Configuration
# ----------------------------------------------------------------------------- #

HISTORY = 120          # nombre d'échantillons gardés pour les graphes
GAME_HISTORY = 6000    # échantillons de jeu gardés (100 ms => ~10 min de jeu)
# Nous échantillonnons RTSS toutes les 100 ms : les « lows » ont besoin de beaucoup
# de points, sinon on les calculerait sur 60 points par minute et le 0.1% low ne
# voudrait plus rien dire.
WIN_POLL_MS = 100
GAME_WARMUP_S = 5.0    # début de session ignoré (lancement + 1er chargement)
GAME_WINDOW_S = 60.0   # fenêtre glissante sur laquelle les « lows » sont calculés
# Une image qui dure plus d'une seconde n'est pas une saccade de jeu : c'est le
# jeu suspendu (alt-tab, pause, chargement). On l'écarte des statistiques, sinon
# elle écrase à elle seule le 0.1% low. Seuil volontairement très conservateur :
# une vraie saccade ressentie reste bien au-dessus de 1 fps.
FREEZE_IGNORE_MS = 1000.0
DEFAULT_INTERVAL_MS = 1000
DEFAULT_FPS_TARGET = 165   # sert d'échelle aux jauges FPS

FPS_STALE_SECONDS = 5  # au-delà, on considère qu'aucun jeu ne tourne

# La mémoire partagée d'Afterburner et celle de RivaTuner (RTSS).
AB_SHARED_MEMORY = ("MAHMSharedMemory", "Global\\MAHMSharedMemory")
RTSS_SHARED_MEMORY = ("RTSSSharedMemoryV2", "Global\\RTSSSharedMemoryV2")
SHM_MAX_SIZE = 64 * 1024 * 1024   # garde-fou : RTSS 7.x occupe ~5,3 Mo
MAX_PATH = 260                    # longueur d'un chemin dans les structures Windows

# Bornes de plausibilité, pour écarter une lecture aberrante plutôt que de
# l'afficher. Un capteur absent vaut souvent 0 ou FLT_MAX, pas None.
FPS_MIN, FPS_MAX = 1.0, 1000.0
TEMP_MIN, TEMP_MAX = 0.0, 150.0


def plausible_fps(fps):
    """Le FPS s'il est crédible, sinon None."""
    return fps if fps is not None and FPS_MIN < fps < FPS_MAX else None


def plausible_temp(t):
    """La température en °C si elle est crédible, sinon None."""
    return t if t is not None and TEMP_MIN < t < TEMP_MAX else None


def asset_dir():
    """Dossier des ressources (icônes).

    Empaquetée par PyInstaller, l'application tourne depuis une copie extraite
    dans un dossier temporaire dont le chemin est donné par sys._MEIPASS ;
    __file__ n'y désigne alors plus le dossier d'installation.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    return bundled if bundled else APP_ROOT


def _num(x):
    """Conversion en float d'une valeur venue de l'extérieur, ou None."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _powershell(command, timeout=3):
    """Sortie d'une commande PowerShell, ou chaîne vide si elle échoue.

    Seul moyen d'interroger WMI/CIM sans dépendance supplémentaire. Coûteux
    (démarrage d'un interpréteur) : réservé aux valeurs lues rarement.
    """
    try:
        return subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout, **_NO_WINDOW,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def app_settings():
    """Réglages mémorisés de l'appli (registre). Un seul endroit
    pour le couple organisation/appli : le changer ici le change partout."""
    from PySide6.QtCore import QSettings   # import local : config reste sans Qt
    return QSettings("CachyMonitor", "CachyMonitor")


def settings_int(s, key):
    """Entier positif mémorisé dans QSettings (texte selon le backend), 0 si
    absent ou illisible. Un seul endroit pour les compteurs de l'appli."""
    try:
        return max(0, int(s.value(key, 0)))
    except (TypeError, ValueError):
        return 0


def _as_bool(v):
    """QSettings rend les booléens en texte selon le backend."""
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return bool(v)
