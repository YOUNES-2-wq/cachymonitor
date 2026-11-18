"""CachyMonitor : relance en administrateur sous Windows (1.7.0).

Le pilote PawnIO, qui donne la température et la consommation du CPU sans
MSI Afterburner, refuse les process non élevés. Choix de Younes (17/11/2026) :
toute l'appli tourne en administrateur plutôt qu'un service séparé.

Plutôt que d'exiger l'élévation dans le manifeste de l'exécutable (ce qui
bloquerait l'appli entière sur un refus), CachyMonitor démarre normalement puis
se relance par l'invite UAC, et seulement si la case des Options est cochée
(décochée par défaut) et que pawnio.elevation_blocker() ne trouve rien à
redire : PawnIO installé, processeur Ryzen, bon module, appli installée dans
Program Files (dossier protégé, sinon un programme ordinaire pourrait remplacer
ses fichiers et profiter du « Oui » à l'UAC ; pour la même raison, jamais depuis
les sources), compte administrateur. Si l'utilisateur refuse, ou si une
condition manque, l'appli continue sans droits, exactement comme en 1.6.0
(Afterburner en secours).

La copie élevée hérite des variables d'environnement de l'utilisateur, que
n'importe quel programme ordinaire peut modifier : harden_environment() les
remplace toutes au démarrage. Seules les options de la ligne de commande
(--debug...) sont transmises volontairement.
"""

import ctypes
import functools
import os
import subprocess
import sys

from .config import IS_WINDOWS, app_settings, settings_int
from .debug import debug_exc
from .debug import enabled as debug_enabled
from . import pawnio, winapi

ELEVATED_FLAG = "--elevated"   # garde-fou : jamais deux relances de suite


def relaunch_command():
    """(programme, arguments) pour relancer la même appli.

    Seule l'option --debug est transmise, jamais les autres arguments reçus :
    n'importe quel programme peut lancer CachyMonitor avec les siens, et Qt en
    lit certains (-platformpluginpath, -plugin...) qui lui feraient charger une
    DLL d'un dossier modifiable sans droits, dans la copie administrateur."""
    args = []
    # L'invite UAC ne transmet pas l'environnement du process qui l'appelle
    # (`set CACHYMONITOR_DEBUG=1` dans un terminal) : la variable de débogage
    # est donc transmise sous forme d'option.
    if debug_enabled():
        args.append("--debug")
    args.append(ELEVATED_FLAG)
    # Toujours l'exécutable installé : elevation_blocker() interdit la relance
    # depuis les sources (fichiers .py modifiables sans droits).
    return sys.executable, args


# Nombre de relances lancées dont la copie élevée n'a pas encore affiché sa
# fenêtre : +1 juste avant chaque relance, remis à 0 par la copie élevée une
# fois sa fenêtre affichée. Un compteur plutôt qu'un oui/non : un double-clic
# pendant que l'invite UAC est ouverte ne passe pas pour un plantage. À
# MAX_PENDING, les dernières copies élevées ont planté avant leur fenêtre : on
# ne recommence pas (sinon UAC puis plantage à chaque lancement, sans issue
# pour un utilisateur ordinaire).
PENDING_KEY = "pawnio_relaunch_pending"
MAX_PENDING = 2
RELAUNCH_FAILED = []   # non vide si la dernière relance a échoué (message à afficher)

def _previous_relaunch_failed():
    """True (et la case est décochée) si les dernières copies élevées n'ont
    jamais affiché leur fenêtre."""
    try:
        s = app_settings()
        if settings_int(s, PENDING_KEY) < MAX_PENDING:
            return False
        s.setValue(PENDING_KEY, 0)
        s.setValue(pawnio.SETTING_KEY, False)
        RELAUNCH_FAILED.append(True)
        return True
    except Exception:
        debug_exc("relance precedente")
        return False


_confirmed = []


def confirm_elevated_start():
    """À appeler par la copie élevée une fois passée l'ouverture de PawnIO (sa
    première lecture comprise), ou à sa fermeture normale : elle n'a pas planté."""
    if elevated_copy() and not _confirmed:
        _confirmed.append(True)     # une seule fois par process
        try:
            # Une relance de moins en attente (pas toutes) : une autre copie
            # élevée qui démarre en même temps reste comptée.
            settings = app_settings()
            settings.setValue(PENDING_KEY, max(0, settings_int(settings, PENDING_KEY) - 1))
        except Exception:
            debug_exc("confirmation de la relance")


def _elevation_requested():
    """La relance est demandée (case cochée, appli lancée sans droits, pas déjà
    relancée, pas désactivée). Sans effet de bord : ne touche pas au compteur."""
    return (IS_WINDOWS
            and ELEVATED_FLAG not in sys.argv
            and os.environ.get("CACHYMONITOR_NO_ELEVATE") != "1"
            and pawnio.setting_enabled()
            and not pawnio.is_admin())


def should_elevate():
    """Toutes les conditions de la relance, en un seul endroit (les mêmes que
    celles qui grisent la case des Options)."""
    return (_elevation_requested()
            and not _previous_relaunch_failed()
            and pawnio.elevation_blocker() is None)


# Une seule copie administrateur à la fois : la copie élevée prend ADMIN_MUTEX
# dès son démarrage (avant Qt) et le garde jusqu'à sa fermeture. Un nouveau
# lancement qui le voit ne relance rien (pas de seconde invite UAC, compteur de
# plantages intact) et le dit (« déjà lancé ») au lieu de disparaître. Un
# double-clic pendant que l'invite UAC est encore ouverte peut en montrer une
# seconde : la seconde copie élevée trouve le verrou pris et se ferme avec le
# même message.
ADMIN_MUTEX = r"Local\CachyMonitor-PawnIO-admin"
STARTED, BUSY = "started", "busy"   # valeurs de relaunch_elevated()
_admin_handle = []
DUPLICATE_ADMIN = []    # non vide : une autre copie administrateur tournait déjà


def _mutex_exists(name):
    """True si un process de la session tient ce verrou. Celui de la copie
    élevée n'est pas ouvrable sans droits : « accès refusé » (5) veut dire
    qu'il existe. Toute autre erreur : considéré absent."""
    k32 = winapi.kernel32_api()
    SYNCHRONIZE = 0x00100000
    handle = k32.OpenMutexW(SYNCHRONIZE, False, name)
    if handle:
        k32.CloseHandle(handle)
        return True
    return ctypes.get_last_error() == 5


def elevated_copy():
    """True dans la copie relancée pour PawnIO : --elevated ET vraiment
    administrateur. L'option seule ne suffit pas (n'importe qui peut taper
    « CachyMonitor.exe --elevated » dans un raccourci)."""
    return IS_WINDOWS and ELEVATED_FLAG in sys.argv and pawnio.is_admin()


def hold_admin_instance():
    """Process administrateur qui ouvrira PawnIO (copie relancée, ou admin lancé
    par l'utilisateur avec la case cochée) : prend ADMIN_MUTEX pour toute sa
    durée de vie. Appelé au tout début (cachymonitor.py, avant Qt). Verrou déjà
    pris : une autre copie administrateur tourne, celle-ci ne s'ouvre pas
    (main() le dit), pas de seconde copie sur PawnIO."""
    if pawnio.env_hardened() and not _admin_handle:
        try:
            handle, existed = winapi.create_mutex(ADMIN_MUTEX)
            if handle:
                _admin_handle.append(handle)    # jamais refermé : rendu à la sortie
            if existed:
                DUPLICATE_ADMIN.append(True)
        except Exception:
            debug_exc("verrou de la copie administrateur")


def _system_dirs():
    """(dossier Windows, System32), donnés par Windows lui-même et pas par les
    variables d'environnement."""
    buf = ctypes.create_unicode_buffer(260)
    k32 = winapi.kernel32_api()
    if not k32.GetSystemWindowsDirectoryW(buf, 260):
        raise OSError("GetSystemWindowsDirectoryW")
    windir = buf.value
    if not k32.GetSystemDirectoryW(buf, 260):
        raise OSError("GetSystemDirectoryW")
    return windir, buf.value


@functools.lru_cache(maxsize=1)
def _userenv_api():
    """userenv avec ses types, déclarés une seule fois (bug n°3)."""
    from ctypes import wintypes
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    userenv.GetUserProfileDirectoryW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
    return userenv


def _profile_dir():
    """Dossier du profil de l'utilisateur, d'après le registre protégé (HKLM
    ProfileList, via userenv), pas d'après USERPROFILE."""
    from ctypes import wintypes
    userenv = _userenv_api()
    with winapi.process_token() as token:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not userenv.GetUserProfileDirectoryW(token, buf, ctypes.byref(size)):
            raise OSError("GetUserProfileDirectoryW")
        return buf.value


# Variables recopiées telles quelles : de simples textes (langue, nom du PC...),
# qui ne désignent ni programme, ni bibliothèque, ni dossier.
_KEEP = {"CACHYMONITOR_DEBUG", "LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES",
         "USERNAME", "USERDOMAIN", "COMPUTERNAME", "NUMBER_OF_PROCESSORS",
         "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "OS",
         # Taille d'affichage de Qt (accessibilité) : des nombres, pas des chemins.
         "QT_SCALE_FACTOR", "QT_ENABLE_HIGHDPI_SCALING", "QT_FONT_DPI",
         "QT_SCREEN_SCALE_FACTORS", "QT_SCALE_FACTOR_ROUNDING_POLICY"}


DEFAULT_WINDIR = r"C:\Windows"   # si Windows ne répond pas : valeur fixe, pas héritée


def _writable_dir(path):
    """True si on peut vraiment créer un fichier dans ce dossier (SystemTemp
    peut exister mais être réservé à SYSTEM sur certains PC)."""
    if not os.path.isdir(path):
        return False
    probe = os.path.join(path, "cachymonitor-%d.tmp" % os.getpid())
    try:
        fd = os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return False
    os.close(fd)
    try:
        os.remove(probe)
    except OSError:
        pass
    return True


def safe_environment(old, windir, system32, profile, program_files, bundle=None,
                     system_folders=None):
    """Nouvel environnement de la copie élevée : liste blanche plutôt que liste
    noire. Toute variable non prévue disparaît (QT_PLUGIN_PATH de l'utilisateur,
    son PATH, CACHYMONITOR_PRESENTMON...) ; les chemins utiles sont recalculés
    d'après Windows et d'après le dossier de l'appli (bundle = sys._MEIPASS, sous
    Program Files). Si Windows ne donne pas ses dossiers, valeurs par défaut fixes."""
    # Pas de _PYI*/_MEI* : la copie élevée les reçoit de HKCU\Environment, que
    # n'importe quel programme sans droits peut écrire ; ses enfants n'en ont pas besoin.
    env = {k: v for k, v in old.items() if k.upper() in _KEEP}
    windir = windir or DEFAULT_WINDIR
    system32 = system32 or os.path.join(windir, "System32")
    powershell_dir = os.path.join(system32, "WindowsPowerShell", "v1.0")
    # Seulement les dossiers de Windows : ni le PATH de l'utilisateur, ni celui
    # du système (des logiciels y ajoutent des dossiers modifiables sans droits).
    path = [system32, windir, os.path.join(system32, "Wbem"), powershell_dir]
    if bundle:
        # Ce que pose le hook PyInstaller de PySide6 (pyi_rth_pyside6), refait
        # à partir du dossier de l'appli : plugins Qt, et DLL (OpenSSL) en tête.
        qt = os.path.join(bundle, "PySide6")
        env["QT_PLUGIN_PATH"] = os.path.join(qt, "plugins")
        env["QML2_IMPORT_PATH"] = os.path.join(qt, "qml")
        path.insert(0, bundle)
    env.update({
        "SystemRoot": windir, "windir": windir, "SystemDrive": windir[:2],
        "PATH": os.pathsep.join(path),
        "PSModulePath": os.path.join(powershell_dir, "Modules"),
        "ComSpec": os.path.join(system32, "cmd.exe"),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
    })
    if profile:
        # Le profil seulement (os.path.expanduser) : pas LOCALAPPDATA, APPDATA ni
        # TEMP de l'utilisateur, dossiers qu'un programme ordinaire peut piéger
        # avec un lien pour détourner une écriture faite en administrateur.
        env["USERPROFILE"] = profile
    # Dossier temporaire réservé au système et aux administrateurs (Windows 11),
    # sinon celui de Windows.
    system_temp = os.path.join(windir, "SystemTemp")
    temp = system_temp if _writable_dir(system_temp) else os.path.join(windir, "Temp")
    env["TEMP"] = env["TMP"] = temp
    if program_files:
        env["ProgramFiles"] = env["ProgramW6432"] = program_files
    env.update(system_folders or {})
    return env


def _system_folders(windir):
    """Autres dossiers communs que des programmes enfants (PowerShell, outils
    NVIDIA) peuvent attendre, lus dans HKLM (modifiable par un administrateur
    seulement). Les dossiers propres à l'utilisateur (APPDATA, LOCALAPPDATA)
    restent absents : il pourrait y piéger une écriture faite en admin."""
    cv = r"SOFTWARE\Microsoft\Windows\CurrentVersion"
    data = winapi.hklm(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList",
                        "ProgramData").replace("%SystemDrive%", windir[:2])
    found = {"ProgramFiles(x86)": winapi.hklm(cv, "ProgramFilesDir (x86)"),
             "CommonProgramFiles": winapi.hklm(cv, "CommonFilesDir"),
             "ProgramData": data, "ALLUSERSPROFILE": data}
    # Seulement des chemins complets, sans variable restée non développée.
    return {k: v for k, v in found.items() if v and "%" not in v and os.path.isabs(v)}


def will_open_pawnio():
    """True si ce process ouvrira le pilote PawnIO : copie relancée pour lui,
    ou appli lancée en administrateur par l'utilisateur avec la case cochée,
    depuis Program Files (ou les sources : test, voir CLAUDE.md), comme la copie
    relancée. Lu sans Qt (registre), pour servir avant harden_environment()."""
    # Copie relancée ou admin lancé par l'utilisateur : même règle, rien ne doit
    # l'empêcher (dossier de l'installateur, module, pilote...). Un exe copié
    # ailleurs et lancé avec --elevated n'ouvre donc pas PawnIO non plus.
    if not (elevated_copy() or (IS_WINDOWS and pawnio.is_admin()
                                and pawnio.setting_in_registry())):
        return False
    return pawnio.elevation_blocker() is None


def qt_arguments():
    """Arguments à donner à QApplication. Process durci (administrateur qui
    ouvre PawnIO) : aucun argument de la ligne de commande, Qt lisant certains
    d'entre eux comme des chemins de plugins (voir relaunch_command)."""
    if pawnio.env_hardened() or elevated_copy():
        return sys.argv[:1]
    return sys.argv


def harden_environment():
    """Dans un process administrateur qui ouvrira PawnIO (will_open_pawnio),
    remplace tout l'environnement par safe_environment(). À appeler avant Qt
    (qui lit les variables QT_* en créant QApplication) et avant toute mesure.

    Seulement lui : quelqu'un qui lance l'appli en administrateur par
    lui-même (UAC désactivé, « Exécuter en tant qu'administrateur ») sans
    avoir coché la case garde son environnement, comme en 1.6.0 (seul le
    journal de débogage change pour tout admin : voir debug.log_path)."""
    opens_pawnio = will_open_pawnio()
    if not (opens_pawnio or elevated_copy()):
        return
    # Une copie relancée pour PawnIO est durcie même si elle ne l'ouvrira finalement
    # pas (registre illisible, module changé entre-temps) : l'environnement est
    # celui de l'utilisateur, et elle tourne en administrateur.
    try:
        windir, system32 = _system_dirs()
    except Exception:
        debug_exc("environnement administrateur (Windows)")
        windir = system32 = None
    try:
        profile = _profile_dir()
    except Exception:
        debug_exc("environnement administrateur (profil)")
        profile = None
    # Les réglages Qt du hook PyInstaller, refaits depuis le dossier de l'appli :
    # c'est celui de l'exécutable qui tourne déjà, aucun risque en plus (et sans
    # eux Qt peut ne pas trouver ses plugins et l'appli ne pas démarrer).
    bundle = getattr(sys, "_MEIPASS", None)
    env = safe_environment(dict(os.environ), windir, system32, profile,
                           pawnio.program_files(), bundle,
                           _system_folders(windir or DEFAULT_WINDIR))
    os.environ.clear()
    os.environ.update(env)
    if opens_pawnio:
        pawnio.mark_env_hardened()      # PawnIO peut désormais être ouvert ici
    # Windows cherche un programme lancé par son seul nom (powershell,
    # nvidia-smi) dans le dossier courant avant System32 : celui-ci doit être
    # protégé, quel que soit le dossier depuis lequel l'appli a été lancée.
    try:
        os.chdir(system32 or os.path.join(env["SystemRoot"], "System32"))
    except OSError:
        debug_exc("environnement administrateur (dossier courant)")


def relaunch_elevated():
    """Tente la relance en administrateur. STARTED si la copie élevée a
    démarré, BUSY si une copie administrateur tourne déjà : dans les deux cas
    l'appelant ne doit pas ouvrir de fenêtre. None sinon (pas demandée, refus
    de l'UAC, erreur) : démarrage normal."""
    if not _elevation_requested():
        return None
    # Avant should_elevate(), qui compte les relances ratées : un double-clic
    # pendant l'invite UAC n'est pas un plantage.
    try:
        if _mutex_exists(ADMIN_MUTEX):
            return BUSY
    except Exception:
        debug_exc("copie administrateur en cours")
    if not should_elevate():
        return None
    return STARTED if _relaunch() else None


def _relaunch():
    settings = None
    started = False
    try:
        exe, args = relaunch_command()
        shell32 = winapi.shell32_api()
        settings = app_settings()
        pending = settings_int(settings, PENDING_KEY)
        settings.setValue(PENDING_KEY, pending + 1)
        settings.sync()     # écrit avant que la copie élevée ne démarre
        SEE_MASK_NOASYNC = 0x100
        info = winapi.ShellExecuteInfo()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = SEE_MASK_NOASYNC
        info.lpVerb, info.lpFile = "runas", exe
        info.lpParameters = subprocess.list2cmdline(args)
        # Dossier de l'exécutable, pas le dossier courant : un lecteur réseau
        # mappé (Z:) n'est pas visible du jeton administrateur.
        info.lpDirectory = os.path.dirname(exe)
        info.nShow = 1      # SW_SHOWNORMAL
        # Échoue (False) sur refus de l'UAC ou erreur.
        started = bool(shell32.ShellExecuteExW(ctypes.byref(info)))
        return started
    except Exception:
        debug_exc("relance en administrateur")
        return started
    finally:
        if settings is not None and not started:
            # Refus de l'UAC ou erreur : aucune copie élevée n'est partie, ce
            # n'est pas un plantage à compter.
            try:
                settings.setValue(PENDING_KEY, max(0, settings_int(settings, PENDING_KEY) - 1))
            except Exception:
                debug_exc("relance en administrateur (compteur)")
