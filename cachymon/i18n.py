"""CachyMonitor : module i18n (voir cachymonitor.py)."""

import os
from PySide6.QtCore import QLocale


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
        "No game detected — launch a game (measured by RivaTuner, or PresentMon "
        "if RivaTuner is not running)":
            "Aucun jeu détecté — lance un jeu (mesuré par RivaTuner, ou par "
            "PresentMon si RivaTuner n'est pas lancé)",
        "PresentMon is not allowed to measure FPS: your account must be in the "
        "\"Performance Log Users\" group. Reinstall CachyMonitor with the "
        "matching option, then sign out and back in.":
            "PresentMon n'a pas le droit de mesurer les FPS : ton compte doit être "
            "dans le groupe « Utilisateurs du journal de performances ». Réinstalle "
            "CachyMonitor avec l'option correspondante, puis déconnecte-toi et "
            "reconnecte-toi.",
        "source: {src}": "source : {src}",
        "No log from MangoHud — logging is off. Enable it below, "
        "or press Shift+F2 in game":
            "Aucun log MangoHud — l'enregistrement est désactivé. Active-le "
            "ci-dessous, ou appuie sur Maj+F2 en jeu",
        "Enable MangoHud logging": "Activer le logging MangoHud",
        "Enable MangoHud logging?": "Activer le logging MangoHud ?",
        "CachyMonitor reads FPS from MangoHud log files, which MangoHud does "
        "not write by default.\n\nThis adds autostart_log=1 to {path} "
        "(a backup is made first). Restart your game afterwards.":
            "CachyMonitor lit les FPS dans les logs de MangoHud, que MangoHud "
            "n'écrit pas par défaut.\n\nCela ajoute autostart_log=1 dans {path} "
            "(une sauvegarde est faite avant). Relance ensuite ton jeu.",
        "Hide MangoHud overlay": "Cacher l'overlay MangoHud",
        "Show MangoHud overlay": "Afficher l'overlay MangoHud",
        "Logging enabled": "Logging activé",
        "Done. Restart your game for MangoHud to pick it up.":
            "C'est fait. Relance ton jeu pour que MangoHud en tienne compte.",
        "Could not edit the MangoHud config": "Impossible de modifier la config MangoHud",
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
        # Manettes
        "CONTROLLER": "MANETTE",
        "No controller detected": "Aucune manette détectée",
        "Wired (USB)": "Câble (USB)",
    },
}


# Langues proposées à l'utilisateur. « système » suit la locale du bureau ; les
# autres sont nommées dans leur propre langue (on ne traduit pas un endonyme).
LANG_MODES = ("systeme", "en", "fr")
LANG_LABELS = {"systeme": "System", "en": "English", "fr": "Français"}
DEFAULT_LANG = "systeme"

_strings = {}


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
