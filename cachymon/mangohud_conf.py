"""CachyMonitor : module mangohud_conf (voir cachymonitor.py)."""

import os

from .config import IS_WINDOWS, LOG_INTERVAL_MS
from .i18n import tr



# ----------------------------------------------------------------------------- #
#  Config MangoHud (Linux) : le FPS vient de ses logs, qu'il n'écrit pas par défaut
# ----------------------------------------------------------------------------- #

MANGOHUD_LOG_DIR = os.path.expanduser("~/.local/share/MangoHud/logs")
MANGOHUD_MIN_DURATION_S = 3600   # en dessous, le log s'arrête en pleine partie


def mangohud_conf_path():
    return (os.environ.get("MANGOHUD_CONFIGFILE")
            or os.path.expanduser("~/.config/MangoHud/MangoHud.conf"))


def _conf_values(lines):
    """Dernière valeur de chaque clé « clé=valeur » (MangoHud garde la dernière)."""
    values = {}
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip()
    return values


def mangohud_logging_enabled():
    """True si la config MangoHud démarre l'enregistrement toute seule."""
    try:
        with open(mangohud_conf_path(), encoding="utf-8") as f:
            val = _conf_values(f.read().splitlines()).get("autostart_log", "0")
        return val.isdigit() and int(val) > 0
    except OSError:
        return False


def enable_mangohud_logging():
    """Active le logging automatique dans la config MangoHud.

    Sauvegarde l'ancien fichier (.cachymonitor.bak), ne touche qu'aux clés
    nécessaires et garde le reste tel quel. Lève OSError en cas d'échec.
    """
    path = mangohud_conf_path()
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        with open(path + ".cachymonitor.bak", "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except FileNotFoundError:
        lines = []
        os.makedirs(os.path.dirname(path), exist_ok=True)

    current = _conf_values(lines)
    wanted = {"autostart_log": "1"}
    duration = current.get("log_duration", "")
    if not duration.isdigit() or int(duration) < MANGOHUD_MIN_DURATION_S:
        wanted["log_duration"] = "86400"
    if "log_interval" not in current:
        wanted["log_interval"] = str(LOG_INTERVAL_MS)
    if "output_folder" not in current:
        wanted["output_folder"] = MANGOHUD_LOG_DIR
        os.makedirs(MANGOHUD_LOG_DIR, exist_ok=True)

    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in wanted:
            continue          # remplacée plus bas, une seule fois
        out.append(line)
    out += [f"{k}={v}" for k, v in wanted.items()]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return path


def mangohud_hud_hidden():
    """True si le HUD est rendu invisible (alpha=0) ; les logs continuent."""
    try:
        with open(mangohud_conf_path(), encoding="utf-8") as f:
            val = _conf_values(f.read().splitlines()).get("alpha", "1")
        return float(val) <= 0
    except (OSError, ValueError):
        return False


def set_mangohud_hud_hidden(hidden):
    """Cache/affiche le HUD via alpha, sans arrêter les mesures ni les logs
    (contrairement à no_display). MangoHud relit le fichier à chaud."""
    path = mangohud_conf_path()
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        with open(path + ".cachymonitor.bak", "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except FileNotFoundError:
        lines = []
        os.makedirs(os.path.dirname(path), exist_ok=True)
    out = [l for l in lines if l.lstrip().startswith("#") or "=" not in l
           or l.split("=", 1)[0].strip() != "alpha"]
    if hidden:
        out.append("alpha=0.0")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def no_game_text():
    """Message « aucun jeu » adapté à l'outil de mesure de la plateforme."""
    if IS_WINDOWS:
        from .game_windows import presentmon_state
        state = presentmon_state()
        if state == "absent":
            return tr("No game detected — launch a game with RivaTuner (RTSS) running")
        text = tr("No game detected — launch a game (measured by RivaTuner, or "
                  "PresentMon if RivaTuner is not running)")
        if state == "denied":
            text += "\n" + tr(
                "PresentMon is not allowed to measure FPS: your account must be in "
                "the \"Performance Log Users\" group. Reinstall CachyMonitor with "
                "the matching option, then sign out and back in.")
        return text
    if not mangohud_logging_enabled():
        return tr("No log from MangoHud — logging is off. Enable it below, "
                  "or press Shift+F2 in game")
    return tr("No game detected — launch a game with MangoHud")
