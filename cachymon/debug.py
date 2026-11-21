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
import threading
import time
import traceback

_enabled = None
_seen = set()
_started = []
# Le thread de mesure et la fenêtre écrivent tous deux : une seule écriture à
# la fois, sinon deux « premières » écritures videraient le fichier tour à tour.
_write_lock = threading.Lock()


def log_path():
    """Fichier du journal, dans %LOCALAPPDATA%/CachyMonitor, ou None.

    En administrateur (copie relancée pour PawnIO, ou appli lancée ainsi par
    l'utilisateur), jamais de fichier : le dossier de l'utilisateur lui appartient,
    et un programme ordinaire pourrait y glisser un lien qui ferait écraser un
    autre fichier avec les droits administrateur. Le journal reste alors à la
    console (s'il y en a une)."""
    from . import pawnio    # import local : pawnio importe ce module
    if pawnio.is_admin():
        return None
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "CachyMonitor", "debug.log")


_log_path_cell = []


def _log_path_once():
    """log_path() calculé une fois qu'il est connu : il ne change pas pendant la
    vie du process (droits, dossier de l'exe). Un « pas de fichier » (None) n'est
    pas gardé : il peut venir d'une lecture passagère du registre."""
    if _log_path_cell:
        return _log_path_cell[0]
    path = log_path()
    if path is not None:
        _log_path_cell.append(path)
    return path


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
    # Sans le texte du message : il varie (chemins, adresses) et ferait
    # grossir le journal sans fin sur une erreur qui se repete 10 fois par seconde.
    # La trace n'est mise en forme qu'apres ce tri (fonction passee a _write).
    _write((context, sys.exc_info()[0]), context, traceback.format_exc)


def debug_msg(context, text):
    """Note un message sans exception en cours (une fois par texte)."""
    if enabled():
        _write((context, text), context, lambda: text + "\n")


def _write(key, context, make_body):
    with _write_lock:
        _write_locked(key, context, make_body)


def unavailable():
    """True si --debug est demandé mais qu'aucun journal ne peut être écrit :
    administrateur hors de Program Files (pas de fichier) et pas de console
    (exe sans fenêtre de commande). L'appli le dit alors au démarrage."""
    try:
        # Seulement l'exe installé : depuis les sources, le message (« installez
        # pour tous les utilisateurs ») ne s'appliquerait pas.
        return (enabled() and getattr(sys, "frozen", False)
                and _log_path_once() is None and sys.stderr is None)
    except Exception:
        return False    # le journal ne doit jamais faire tomber l'appli


def _write_locked(key, context, make_body):
    try:
        if key in _seen:
            return
        _seen.add(key)
        entry = "[%s] %s\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), context, make_body())
        path = _log_path_once()
        if path is None:
            # Administrateur hors de Program Files (sources depuis un terminal
            # admin) : pas de fichier, mais la console du terminal, si elle existe.
            if sys.stderr is not None:
                sys.stderr.write(entry)
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Premiere ecriture de cette session : on repart d'un fichier neuf, pour que
        # le journal joint a une issue ne melange pas plusieurs lancements.
        mode = "a" if _started else "w"
        _started.append(True)
        with open(path, mode, encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass            # le journal ne doit jamais, lui non plus, faire tomber l'appli
