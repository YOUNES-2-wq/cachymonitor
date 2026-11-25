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
        "System: {value}": "Système : {value}",
        "Dark": "Sombre",
        "Light": "Clair",
        "Black (OLED)": "Noir (OLED)",
        "Windows 11": "Windows 11",
        "Midnight": "Midnight",
        "Graphite": "Graphite",
        "Aurora": "Aurora",
        "Emerald": "Emerald",
        "Nord": "Nord",
        "Dracula": "Dracula",
        "Catppuccin Mocha": "Catppuccin Mocha",
        "Tokyo Night": "Tokyo Night",
        "Gruvbox": "Gruvbox",
        "Rosé Pine": "Rosé Pine",
        "One Dark": "One Dark",
        "Solarized Dark": "Solarized Dark",
        "Synthwave": "Synthwave",
        "Cyberpunk": "Cyberpunk",
        "Claude": "Claude",
        "Catppuccin Latte": "Catppuccin Latte",
        "Nord Light": "Nord Light",
        "Solarized Light": "Solarized Light",
        "Calm background while gaming": "Fond calme pendant le jeu",
        "Glass intensity": "Intensité du verre",
        "Accent colour": "Couleur d'accent",
        "Coral": "Corail",
        "Cyan": "Cyan",
        "Violet": "Violet",
        "Green": "Vert",
        "Amber": "Ambre",
        "Rose": "Rose",
        "Animated background (Claude theme)": "Fond animé (thème Claude)",
        "Compact mode": "Mode compact",
        "Cards": "Cartes",
        "Appearance": "Apparence",
        "Controllers": "Manettes",
        "Interval": "Intervalle",
        "FPS target": "Cible FPS",
        "Theme": "Thème",
        "Language": "Langue",
        "« System » follows the desktop language":
            "« Système » suit la langue du bureau",
        "Always on top": "Au-dessus des autres fenêtres",
        # Fenêtre « À propos »
        "About": "À propos",
        "About CachyMonitor": "À propos de CachyMonitor",
        "Version {version}": "Version {version}",
        "Lightweight gaming system monitor for Windows 11: CPU, GPU, "
        "RAM, VRAM, temperatures, FPS and controller battery.":
            "Moniteur système léger pour le jeu, sous Windows 11 : CPU, GPU, "
            "RAM, VRAM, températures, FPS et batterie de la manette.",
        "Made by {author}, free and open source (MIT license).":
            "Créé par {author}, libre et gratuit (licence MIT).",
        "Source code, updates and bug reports:":
            "Code source, mises à jour et signalement de bugs :",
        "Administrator mode: {value}": "Mode administrateur : {value}",
        "yes": "oui",
        "no": "non",
        # Case PawnIO (Windows, 1.7.0)
        "CPU temperature via PawnIO (asks for administrator rights at launch)":
            "Température CPU par PawnIO (demande les droits administrateur au lancement)",
        "Reads the CPU temperature and power without MSI Afterburner. Windows will ask "
        "for confirmation (UAC) each time CachyMonitor starts. Takes effect at the next "
        "launch.":
            "Lit la température et la consommation du CPU sans MSI Afterburner. Windows "
            "demandera une confirmation (UAC) à chaque démarrage de CachyMonitor. Prend effet "
            "au prochain lancement.",
        "This takes effect the next time CachyMonitor starts.":
            "Ce changement prendra effet au prochain démarrage de CachyMonitor.",
        "The PawnIO driver is not installed.": "Le pilote PawnIO n'est pas installé.",
        "From the sources, start CachyMonitor from an administrator terminal.":
            "Depuis les sources, lancez CachyMonitor depuis un terminal administrateur.",
        "PawnIO could not read this processor. The option has been turned off: "
        "CachyMonitor will no longer ask for administrator rights.":
            "PawnIO n'a pas pu lire ce processeur. L'option a été désactivée : "
            "CachyMonitor ne demandera plus les droits administrateur.",
        "The last start in administrator mode (PawnIO) failed. The option has been "
        "turned off: CachyMonitor starts normally again.":
            "Le dernier démarrage en mode administrateur (PawnIO) a échoué. L'option a été "
            "désactivée : CachyMonitor démarre de nouveau normalement.",
        "PawnIO could not be started (the PawnIO driver may be too old: uninstall "
        "it in the Windows settings, then install the latest version from "
        "pawnio.eu). The option has been turned off: CachyMonitor will no longer "
        "ask for administrator rights.":
            "PawnIO n'a pas pu démarrer (le pilote PawnIO est peut-être trop ancien : "
            "désinstallez-le dans les paramètres de Windows, puis installez la dernière "
            "version depuis pawnio.eu). L'option a été désactivée : CachyMonitor ne "
            "demandera plus les droits administrateur.",
        "CachyMonitor is already running in administrator mode (PawnIO), or is "
        "starting. If its window does not appear, close CachyMonitor in the Task "
        "Manager, then start it again.":
            "CachyMonitor tourne déjà en mode administrateur (PawnIO), ou est en train "
            "de démarrer. Si sa fenêtre n'apparaît pas, fermez CachyMonitor dans le "
            "Gestionnaire des tâches, puis relancez-le.",
        "PawnIO is turned off. CachyMonitor will start without "
        "administrator rights next time.":
            "PawnIO est désactivé. CachyMonitor démarrera sans les droits "
            "administrateur la prochaine fois.",
        "The AMD module next to CachyMonitor is damaged or has been replaced: "
        "reinstall CachyMonitor. The option has been turned off: CachyMonitor "
        "will no longer ask for administrator rights.":
            "Le module AMD à côté de CachyMonitor est abîmé ou a été remplacé : "
            "réinstallez CachyMonitor. L'option a été désactivée : CachyMonitor ne "
            "demandera plus les droits administrateur.",
        "The PawnIO driver was not found. Install it from pawnio.eu, then tick "
        "the option again. The option has been turned off: CachyMonitor will "
        "no longer ask for administrator rights.":
            "Le pilote PawnIO est introuvable. Installez-le depuis pawnio.eu, puis "
            "recochez l'option. L'option a été désactivée : CachyMonitor ne "
            "demandera plus les droits administrateur.",
        "Debug log unavailable: in administrator mode, CachyMonitor does not write "
        "a log file. Start it without administrator rights to get one.":
            "Journal de débogage indisponible : en mode administrateur, CachyMonitor "
            "n'écrit pas de fichier. Lancez-le sans les droits administrateur pour en avoir un.",
        "Could not check your Windows account. Open the Options again to retry.":
            "Impossible de vérifier votre compte Windows. Rouvrez les Options pour réessayer.",
        "PawnIO could not be opened right now. CachyMonitor keeps "
        "using MSI Afterburner for the CPU temperature, and will try "
        "PawnIO again at the next start.":
            "PawnIO n'a pas pu s'ouvrir pour l'instant. CachyMonitor continue "
            "d'utiliser MSI Afterburner pour la température CPU, et réessaiera "
            "PawnIO au prochain démarrage.",
        "Your Windows account is not an administrator.":
            "Votre compte Windows n'est pas administrateur.",
        "Only AMD Ryzen processors are supported.":
            "Seuls les processeurs AMD Ryzen sont pris en charge.",
        "The AMD module is missing next to CachyMonitor.":
            "Le module AMD manque à côté de CachyMonitor.",
        "The AMD module is not the expected one.": "Le module AMD n'est pas celui attendu.",
        "CachyMonitor must be installed for all users (in Program Files) to run as "
        "administrator.":
            "CachyMonitor doit être installé pour tous les utilisateurs (dans Program Files) "
            "pour tourner en administrateur.",
        "Measurement refresh rate": "Fréquence de rafraîchissement des mesures",
        "Scales the FPS colours and marks the frametime graph":
            "Sert d'échelle aux couleurs FPS et de repère sur le graphe de frametime",
        "« System » follows the desktop light/dark setting":
            "« Système » suit le thème clair/sombre du bureau",
        # Panneau de jeu
        "IN GAME": "EN JEU",
        "AVERAGE ({win:.0f} s)": "MOYENNE ({win:.0f} s)",
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
        # Mise à jour
        "Check for updates at startup": "Rechercher les mises à jour au démarrage",
        "Asks GitHub whether a newer version exists. Nothing is sent about your PC.":
            "Demande à GitHub s'il existe une version plus récente. Rien n'est envoyé sur votre PC.",
        "Hide until the next version": "Masquer jusqu'à la prochaine version",
        "Downloading version {version}…": "Téléchargement de la version {version}…",
        "Installing version {version}…": "Installation de la version {version}…",
        "Version {version} is available.": "La version {version} est disponible.",
        "Version {version} is available. Restart CachyMonitor without administrator "
        "rights to update.":
            "La version {version} est disponible. Relancez CachyMonitor sans les droits "
            "administrateur pour la mettre à jour.",
        "Update now": "Mettre à jour",
        "Open the download page": "Ouvrir la page de téléchargement",
        "Cancel": "Annuler",
        "Retry": "Réessayer",
        "The update failed ({reason}).": "La mise à jour a échoué ({reason}).",
        "Windows did not start the installer": "Windows n'a pas lancé l'installateur",
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

    Windows ne définit pas les variables d'environnement POSIX (LANG...), sauf
    si l'utilisateur les pose : à défaut, on prend la locale que Qt obtient de l'OS.
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
