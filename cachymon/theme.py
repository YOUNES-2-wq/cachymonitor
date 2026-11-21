"""CachyMonitor : module theme (voir cachymonitor.py)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from .i18n import DEFAULT_LANG, set_language



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

    Qt 6.5+ rapporte le réglage. Quand il répond « inconnu », le registre
    donne la réponse directement.
    """
    scheme = QApplication.instance().styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Light:
        return "clair"
    if scheme == Qt.ColorScheme.Dark:
        return "sombre"
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
