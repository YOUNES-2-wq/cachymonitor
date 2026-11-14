"""CachyMonitor : journal de debogage (voir cachymonitor.py).

Beaucoup de lecteurs de capteurs avalent leurs erreurs a dessein : un capteur
exotique ne doit jamais faire tomber l'application. Revers de la medaille, quand
quelque chose ne s'affiche pas sur une machine qu'on ne possede pas, rien ne dit
pourquoi. Avec l'option --debug (ou la variable CACHYMONITOR_DEBUG=1), chaque
erreur avalee est ecrite, une seule fois, dans un fichier a joindre a une issue.

Sans l'option, ce module ne fait strictement rien.
"""

import os
import sys
import time
import traceback

from .config import IS_WINDOWS

_enabled = None
_seen = set()
_started = []


def log_path():
    """Fichier du journal, dans le dossier de cache de l'utilisateur."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "CachyMonitor", "debug.log")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "cachymonitor", "debug.log")


def enabled():
    global _enabled
    if _enabled is None:
        _enabled = ("--debug" in sys.argv
                    or os.environ.get("CACHYMONITOR_DEBUG", "") not in ("", "0"))
    return _enabled


def debug_exc(context):
    """A appeler dans un `except` : note l'erreur en cours (une fois par cause)."""
    if not enabled():
        return
    try:
        exc = sys.exc_info()
        # Sans le texte du message : il varie (chemins, adresses) et ferait
        # grossir le journal sans fin sur une erreur qui se repete 10 fois par seconde.
        key = (context, exc[0])
        if key in _seen:
            return
        _seen.add(key)
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Premiere ecriture de cette session : on repart d'un fichier neuf, pour que
        # le journal joint a une issue ne melange pas plusieurs lancements.
        mode = "a" if _started else "w"
        _started.append(True)
        with open(path, mode, encoding="utf-8") as f:
            f.write("[%s] %s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), context,
                                       traceback.format_exc()))
    except Exception:
        pass            # le journal ne doit jamais, lui non plus, faire tomber l'appli
