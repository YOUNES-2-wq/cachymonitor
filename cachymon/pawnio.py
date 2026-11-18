"""CachyMonitor : température et consommation CPU par le pilote PawnIO (Windows, AMD).

PawnIO (namazso, pilote signé Microsoft) exécute de petits « modules » signés
qui n'autorisent que des lectures précises. Le module AMDFamily17 (Ryzen Zen 1
à Zen 5) expose deux fonctions utilisées ici, en lecture seule :
  - ioctl_read_smn : registre interne du processeur, d'où vient la température ;
  - ioctl_read_msr : compteur d'énergie du processeur, d'où vient la consommation.
Rien n'est jamais écrit dans le processeur.

Le pilote refuse tout process non élevé (« accès refusé ») : CachyMonitor se
relance donc en administrateur quand PawnIO est installé (voir elevation.py).
Comme ce code tourne en administrateur, rien n'est chargé d'un endroit modifiable
sans droits sans être vérifié : la DLL vient du dossier du pilote (Program Files),
le module est contrôlé par son empreinte SHA256.
Sans PawnIO, sans droits, ou sur Intel, tout renvoie None et l'appelant garde
ses sources habituelles (MSI Afterburner, LibreHardwareMonitor...).

Vérifié le 17/11/2026 sur Ryzen 5 5600 : température identique à Afterburner à
0,1 °C près, consommation à 1 W près.
"""

import ctypes
import hashlib
import os
import sys
import threading
import time

from .config import APP_ROOT, IS_WINDOWS
from .debug import debug_exc, debug_msg
from .winapi import (advapi32_api, cache_final, cache_known, create_mutex,
                     hklm, kernel32_api, process_token, shell32_api)

MODULE_AMD = "AMDFamily17.bin"
# Empreinte du module embarqué (PawnIO.Modules 0.2.11, vérifié par build.ps1).
# Vérifiée aussi ici, car ce fichier est chargé par un process administrateur :
# un module remplacé dans le dossier de l'appli est refusé.
MODULE_AMD_SHA256 = "dae74615761b78bdf064dfb3e136252ddcc6fc727d88f14738d0e5800d427a91"

# Registres AMD (mêmes valeurs que LibreHardwareMonitor et le pilote Linux k10temp).
SMN_THM_TCON_CUR_TMP = 0x00059800   # température Tctl
TEMP_RANGE_SEL = 0x80000            # bit « plage -49 °C »
TEMP_TJ_SEL = 0x30000               # ou ces deux bits à 1 (k10temp)
STALE_S = 5.0                       # durée de vie de la dernière valeur lue
# Au-delà, deux relevés d'énergie sont trop éloignés pour une moyenne fiable :
# le compteur fait un tour en ~11 min à 100 W (65,5 kJ à 15,3 µJ par unité).
MAX_ENERGY_GAP_S = 30.0
# STATUS_NOT_SUPPORTED, renvoyé par le main() du module sur un processeur qu'il
# ne gère pas, tel quel ou converti en HRESULT (HRESULT_FROM_NT).
HR_NOT_SUPPORTED = (0xC00000BB, 0xD00000BB)
MSR_PWR_UNIT = 0xC0010299           # unité du compteur d'énergie
MSR_PKG_ENERGY_STAT = 0xC001029B    # énergie consommée par tout le processeur

# Ces processeurs ajoutent un décalage à Tctl pour la ventilation : on l'ôte
# pour afficher la vraie température. Table et règle du pilote Linux k10temp
# (tctl_offset_table, recherche du nom complet dans le libellé) : un « PRO
# 2700X » n'y figure pas et n'a pas de décalage.
TCTL_OFFSETS = (("AMD Ryzen 5 1600X", 20), ("AMD Ryzen 7 1700X", 20),
                ("AMD Ryzen 7 1800X", 20), ("AMD Ryzen 7 2700X", 10),
                ("AMD Ryzen Threadripper 19", 27), ("AMD Ryzen Threadripper 29", 27))


def decode_tctl(raw, offset=0.0):
    """Température en °C à partir du registre THM_TCON_CUR_TMP.

    Plage « -49 °C » signalée de deux façons selon les modèles, comme dans le
    pilote Linux k10temp : le bit RANGE_SEL, ou les deux bits TJ_SEL à 1."""
    temp = ((raw >> 21) & 0x7FF) / 8.0
    if raw & TEMP_RANGE_SEL or (raw & TEMP_TJ_SEL) == TEMP_TJ_SEL:
        temp -= 49.0
    return temp - offset


def energy_watts(e0, e1, unit_j, seconds):
    """Puissance moyenne entre deux relevés du compteur d'énergie (32 bits,
    il repart de zéro quand il déborde)."""
    if seconds <= 0:
        return None
    return ((e1 - e0) & 0xFFFFFFFF) * unit_j / seconds


def is_admin():
    if not IS_WINDOWS:
        return False
    try:
        return bool(shell32_api().IsUserAnAdmin())
    except Exception:
        return False


TOKEN_LIMITED = 3   # TokenElevationTypeLimited : compte admin, jeton restreint par l'UAC


@cache_known
def token_elevation_type():
    """Type d'élévation du jeton du process (1 = sans UAC, 2 = élevé, 3 = restreint),
    ou None si illisible. Un compte standard donne 1 : l'UAC y demanderait le mot
    de passe d'un AUTRE compte, et l'appli tournerait sous ce compte-là. Gardé en
    cache une fois lu ; un échec n'est pas gardé (nouvel essai aux Options)."""
    return _read_token_type()


def _read_token_type():
    if not IS_WINDOWS:
        return None
    try:
        from ctypes import wintypes
        advapi32 = advapi32_api()
        TOKEN_ELEVATION_TYPE = 18
        with process_token() as token:
            value, size = ctypes.c_int(), wintypes.DWORD()
            if not advapi32.GetTokenInformation(token, TOKEN_ELEVATION_TYPE, ctypes.byref(value),
                                                ctypes.sizeof(value), ctypes.byref(size)):
                return None
            return value.value or None
    except Exception:
        debug_exc("type de jeton UAC")
        return None


@cache_known
def program_files():
    """Dossier Program Files 64 bits, lu dans le registre (jamais dans
    l'environnement : voir hklm). Ne change pas pendant la session une fois lu ;
    un registre muet (échec passager) rend "" et n'est pas gardé en cache."""
    return hklm(r"SOFTWARE\Microsoft\Windows\CurrentVersion", "ProgramFilesDir") or None


def protected_folder(path):
    """True si path est sous Program Files, que seul un administrateur peut
    modifier. Une appli qui se relance en administrateur ne doit pas tourner
    depuis un dossier qu'un programme ordinaire pourrait altérer, ni charger
    une DLL qui en vient."""
    root = program_files()
    if not root:
        return False
    root = os.path.normcase(os.path.abspath(root)).rstrip("\\/") + os.sep
    return os.path.normcase(os.path.abspath(path)).startswith(root)


APP_UNINSTALL_KEY = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
                     r"\{61F32A52-2721-4AFB-8D69-CB8DF4E34FAD}_is1")   # AppId du .iss


def installed_here(exe):
    """True si exe est dans LE dossier où l'installateur de CachyMonitor (pour
    tous les utilisateurs) l'a installé, d'après sa clé de désinstallation
    dans HKLM (modifiable seulement par un administrateur). Être quelque part
    sous Program Files ne suffit pas : un logiciel tiers peut laisser son
    propre sous-dossier modifiable par tous, et une copie de CachyMonitor posée
    là profiterait du « Oui » à l'UAC."""
    location = hklm(APP_UNINSTALL_KEY, "InstallLocation")
    if not location or not protected_folder(location):
        return False
    norm = lambda p: os.path.normcase(os.path.abspath(p)).rstrip("\\/")  # noqa: E731
    return norm(os.path.dirname(exe)) == norm(location)


def pawnio_dll():
    """Chemin de PawnIOLib.dll, ou None. Toujours un chemin complet dans le
    dossier d'installation du pilote, et seulement s'il est sous Program Files :
    jamais une DLL cherchée dans le dossier de l'appli ou ailleurs."""
    if not IS_WINDOWS:
        return None
    folders = [hklm(r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO",
                     "InstallLocation")]
    if program_files():
        folders.append(os.path.join(program_files(), "PawnIO"))
    for folder in folders:
        if not folder:
            continue
        path = os.path.join(folder, "PawnIOLib.dll")
        if os.path.isabs(path) and protected_folder(path) and os.path.isfile(path):
            return path
    return None


def installed():
    """True si le pilote PawnIO est installé (sa bibliothèque est présente)."""
    return pawnio_dll() is not None


def cpu_registry(value):
    """Valeur de la description du processeur 0 (nom, fabricant), ou ""."""
    return hklm(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", value)


def cpu_family(identifier):
    """Famille du processeur d'après « AMD64 Family 25 Model 33 Stepping 2 », ou None."""
    import re
    match = re.search(r"\bFamily (\d+)\b", identifier or "")
    return int(match.group(1)) if match else None


@cache_known
def cpu_is_ryzen():
    """True pour un AMD de famille 17h à 1Ah (Zen 1 à Zen 5) : les seuls que le
    module AMDFamily17 accepte (voir son main()). Un FX ou un Phenom n'en est pas.
    None si le registre n'a pas répondu (échec passager, pas « pas un Ryzen »).
    En cache une fois lu : le processeur ne change pas pendant la session."""
    vendor = cpu_registry("VendorIdentifier")
    if not vendor:
        return None
    family = cpu_family(cpu_registry("Identifier"))
    return vendor == "AuthenticAMD" and family is not None and 0x17 <= family <= 0x1A


def ryzen_cpu():
    """cpu_is_ryzen(), False si le registre n'a pas répondu."""
    return bool(cpu_is_ryzen())


@cache_final
def elevation_blocker():
    """Raison (texte anglais, à traduire par tr) pour laquelle le mode
    administrateur n'apporterait rien ou serait imprudent ; None s'il est possible.
    Évite une invite UAC inutile, par exemple sur un PC Intel. En cache (lit le
    registre et hache le module) mais seulement quand la réponse est définitive :
    un registre ou un jeton illisible (échec passager) est réessayé à l'appel
    suivant. La fenêtre vide le cache quand on ouvre les Options."""
    reason = _blocker_reason()
    transient = (cpu_is_ryzen() is None or not program_files()
                 or (reason is not None and reason.startswith("Could not check")))
    return reason, not transient


def _blocker_reason():
    # Le processeur d'abord : sur un PC Intel, inutile d'inviter à installer
    # un pilote qui ne servirait à rien.
    if not ryzen_cpu():
        return "Only AMD Ryzen processors are supported."
    if not installed():
        return "The PawnIO driver is not installed."
    path = _module_path()
    if path is None:
        return "The AMD module is missing next to CachyMonitor."
    try:
        with open(path, "rb") as f:
            if not module_ok(f.read()):
                return "The AMD module is not the expected one."
    except OSError:
        return "The AMD module is missing next to CachyMonitor."
    if not getattr(sys, "frozen", False):
        # Depuis les sources, les .py sont modifiables sans droits : jamais de
        # relance automatique. Pour tester PawnIO, lancer depuis un terminal admin.
        return None if is_admin() else (
            "From the sources, start CachyMonitor from an administrator terminal.")
    if not installed_here(sys.executable):      # inclut protected_folder
        # Même pour un admin lancé par l'utilisateur : PawnIO et PresentMon ne
        # tournent en administrateur que depuis le dossier protégé où
        # l'installateur (pour tous les utilisateurs) a posé CachyMonitor.
        return ("CachyMonitor must be installed for all users (in Program Files) "
                "to run as administrator.")
    if is_admin():
        return None     # déjà administrateur : rien à relancer, PawnIO lisible
    token_type = token_elevation_type()
    if token_type is None:
        # Jeton illisible (échec passager) : on ne conclut rien sur le compte.
        # Pas gardé en cache (token_elevation_type), réessayé aux Options.
        return "Could not check your Windows account. Open the Options again to retry."
    if token_type != TOKEN_LIMITED:
        return "Your Windows account is not an administrator."
    return None


def _module_path():
    """Le module AMD est posé à côté de CachyMonitor.exe par l'installateur ;
    depuis les sources, à la racine du dépôt (copie locale, hors git)."""
    if getattr(sys, "frozen", False):
        path = os.path.join(os.path.dirname(sys.executable), MODULE_AMD)
    else:
        path = os.path.join(APP_ROOT, MODULE_AMD)
    return path if os.path.isfile(path) else None


def module_ok(blob):
    """True si le module est exactement celui qui a été vérifié."""
    return hashlib.sha256(blob).hexdigest() == MODULE_AMD_SHA256


# Posé par elevation.harden_environment() une fois l'environnement remplacé :
# PawnIO n'est ouvert que dans un process durci dès son démarrage (copie
# relancée, ou admin lancé par l'utilisateur avec la case déjà cochée).
_env_hardened = False


def mark_env_hardened():
    global _env_hardened
    _env_hardened = True


def env_hardened():
    return _env_hardened


def reset_env_hardened():
    """Tests seulement : remet le drapeau à zéro."""
    global _env_hardened
    _env_hardened = False


SETTING_KEY = "pawnio_admin"   # case « Température CPU par PawnIO » des Options


def setting_in_registry():
    """La case PawnIO lue directement dans le registre (là où QSettings la
    range sous Windows), sans charger Qt : sert avant harden_environment().
    Ne sert qu'à durcir davantage, jamais à relâcher une protection."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\CachyMonitor\CachyMonitor") as key:
            value = winreg.QueryValueEx(key, SETTING_KEY)[0]
        return str(value).strip().lower() in ("true", "1")
    except (OSError, ImportError):
        return False


def setting_enabled():
    """La case des Options, décochée par défaut : sans elle, jamais d'invite UAC
    ni d'ouverture du pilote, même si PawnIO a été installé par un autre
    logiciel (FanControl, LHM...) ou si l'appli tourne déjà en administrateur.
    Réglage illisible : comme décochée."""
    try:
        from .config import _as_bool, app_settings
        return _as_bool(app_settings().value(SETTING_KEY, False))
    except Exception:
        debug_exc("reglage mode administrateur")
        return False


def _note_failure(message):
    """Note un échec définitif dans le journal de débogage."""
    debug_msg("PawnIO (echec definitif)", message)


def _tctl_offset():
    name = cpu_registry("ProcessorNameString")
    for model, offset in TCTL_OFFSETS:
        if model in name:
            return float(offset)
    return 0.0


class PawnIoCpu:
    """Température et consommation CPU AMD via PawnIO. Ouvert au premier appel,
    une seule fois par session : un échec (pas de pilote, pas de case, processeur
    refusé, pilote qui ne répond pas...) désactive PawnIO jusqu'au prochain
    lancement, Afterburner reprend. La cause est gardée (failure_reason) pour que
    la fenêtre la dise."""

    # Causes d'échec (failure_reason). Les quatre premières sont durables (la case
    # est décochée) ; les deux dernières peuvent être passagères (la case reste).
    UNSUPPORTED, BAD_MODULE, MISSING_DRIVER, DRIVER_REFUSED = (
        "unsupported", "bad_module", "missing_driver", "driver_refused")
    PCI_BUSY, NO_RESPONSE = "pci_busy", "no_response"
    TRANSIENT = (PCI_BUSY, NO_RESPONSE)

    def __init__(self):
        # Le pilote n'est touché que par le thread de mesure (temp, power), sous
        # _lock. La fenêtre ne lit que _state et _failure (de simples
        # affectations) : la cause est écrite AVANT _state, elle ne voit donc
        # jamais un échec sans sa cause.
        self._lock = threading.Lock()
        self._state = None      # None = pas encore essayé, True = ouvert, False = indisponible
        self._failure = None
        self._lib = self._handle = self._mutex = None
        self._k32 = kernel32_api() if IS_WINDOWS else None
        self._offset = 0.0
        self._unit = None
        self._energy = None     # (compteur, instant) du relevé précédent
        self._last_temp = self._last_power = None   # (valeur, instant)

    def _fail(self, reason, note=None):
        """Échec de l'ouverture : cause posée, notée au journal."""
        if note:
            _note_failure(note)
        self._failure = reason
        return False

    def _open(self):
        # Seulement si l'utilisateur l'a demandé (case cochée) et sur un Ryzen :
        # quelqu'un qui lance l'appli en administrateur sans la case garde la
        # 1.6.0, sans pilote ouvert ni verrou partagé avec HWiNFO.
        if not (is_admin() and env_hardened()):
            return False        # pas demandé : rien d'anormal, rien à signaler
        if not cpu_is_ryzen():
            return False        # pas un Ryzen (ou registre muet) : PawnIO ne sert pas ici
        if not setting_enabled():
            return False
        # Demandé mais impossible : noté, et la fenêtre dit pourquoi.
        dll = pawnio_dll()      # résolu une seule fois
        if dll is None:
            return self._fail(self.MISSING_DRIVER, "PawnIOLib.dll introuvable")
        path = _module_path()
        if not path:
            return self._fail(self.BAD_MODULE, "module PawnIO absent : " + MODULE_AMD)
        try:
            with open(path, "rb") as f:
                blob = f.read()
        except OSError:
            return self._fail(self.BAD_MODULE, "module PawnIO illisible : " + path)
        if not module_ok(blob):
            return self._fail(self.BAD_MODULE, "module PawnIO inattendu, refusé : " + path)
        # Dépendances de la DLL cherchées seulement dans son propre dossier et
        # dans System32, jamais dans celui de l'appli.
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR, LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x100, 0x800
        H = ctypes.c_void_p
        try:
            lib = ctypes.WinDLL(dll, winmode=LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR
                                | LOAD_LIBRARY_SEARCH_SYSTEM32)
            # Types déclarés partout : sans eux ctypes tronque les handles 64 bits (bug n°3).
            lib.pawnio_open.argtypes = [ctypes.POINTER(H)]
            lib.pawnio_load.argtypes = [H, ctypes.c_char_p, ctypes.c_size_t]
            lib.pawnio_execute.argtypes = [H, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint64),
                                           ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint64),
                                           ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
            lib.pawnio_close.argtypes = [H]
            for f in (lib.pawnio_open, lib.pawnio_load, lib.pawnio_execute, lib.pawnio_close):
                f.restype = ctypes.c_long
        except (OSError, AttributeError):
            # DLL non chargeable, ou trop ancienne (fonction manquante).
            debug_exc("PawnIO (bibliotheque)")
            return self._fail(self.DRIVER_REFUSED, "PawnIOLib.dll inutilisable : " + dll)

        handle = H()
        hr = lib.pawnio_open(ctypes.byref(handle)) & 0xFFFFFFFF
        if hr != 0 or not handle.value:
            if handle.value:
                lib.pawnio_close(handle)
            # Souvent passager (pilote pas encore démarré à l'ouverture de la
            # session) : _ready() le range en NO_RESPONSE.
            raise OSError("pawnio_open : %#x" % hr)
        try:
            hr = lib.pawnio_load(handle, blob, len(blob)) & 0xFFFFFFFF
            if hr != 0:
                lib.pawnio_close(handle)
                if hr in HR_NOT_SUPPORTED:
                    # Le main() du module refuse ce processeur (pas un Ryzen).
                    return self._fail(self.UNSUPPORTED)
                # Autre cause (pilote PawnIO trop ancien pour ce module...).
                return self._fail(self.DRIVER_REFUSED, "pawnio_load : %#x" % hr)
            self._lib, self._handle = lib, handle
            try:
                self._mutex = self._pci_mutex()
            except OSError:
                # Verrou créé par un autre logiciel avec des droits plus
                # stricts : Afterburner prend le relais cette fois-ci.
                debug_exc("PawnIO (verrou PCI)")
                lib.pawnio_close(handle)
                self._lib = self._handle = None
                return self._fail(self.PCI_BUSY, "verrou Global\\Access_PCI refuse")
            self._offset = _tctl_offset()
            self._unit = self._energy_unit()
            return True
        except Exception:
            # Rien laissé ouvert pour rien jusqu'à la fin de la session.
            lib.pawnio_close(handle)
            if self._mutex:
                self._k32.CloseHandle(self._mutex)
            self._lib = self._handle = self._mutex = None
            raise

    def _energy_unit(self):
        """Unité du compteur d'énergie en joules, ou None : la température reste
        lue par PawnIO, la conso est laissée à Afterburner. Jamais d'exception :
        un échec ici ne doit pas couper la température."""
        try:
            esu = (self._call(b"ioctl_read_msr", MSR_PWR_UNIT) >> 8) & 0x1F
        except Exception:
            debug_exc("PawnIO (unite d'energie)")
            return None
        # 0 donnerait 1 J par incrément, absurde (16 sur les Ryzen, soit 15,3 µJ).
        return 1.0 / (1 << esu) if esu else None

    def _pci_mutex(self):
        """Afterburner, HWiNFO et LibreHardwareMonitor lisent le même registre
        par la même paire index/donnée : ce verrou commun évite de se croiser.
        Sans lui, aucune lecture de température (voir temp())."""
        k32 = self._k32
        name = "Global\\Access_PCI"
        # Ouvert à tous les comptes (comme LibreHardwareMonitor) : créé par nous
        # en administrateur, il ne doit pas fermer l'accès aux autres outils.
        mutex, _ = create_mutex(name, shared=True)   # déjà créé par un autre : normal
        if not mutex:
            # Déjà créé par un autre logiciel avec des droits plus stricts :
            # on demande seulement de quoi attendre et relâcher le verrou.
            SYNCHRONIZE, MUTEX_MODIFY_STATE = 0x00100000, 0x0001
            mutex = k32.OpenMutexW(SYNCHRONIZE | MUTEX_MODIFY_STATE, False, name)
        if not mutex:
            raise OSError("verrou Global\\Access_PCI inaccessible (erreur %d)"
                          % ctypes.get_last_error())
        return mutex

    def _call(self, name, arg):
        inp = (ctypes.c_uint64 * 1)(arg)
        out = (ctypes.c_uint64 * 1)()
        n = ctypes.c_size_t()
        hr = self._lib.pawnio_execute(self._handle, name, inp, 1, out, 1, ctypes.byref(n))
        if hr != 0:
            raise OSError("PawnIO %s : %#x" % (name.decode(), hr & 0xFFFFFFFF))
        return out[0]

    def _ready(self):
        """Ouvre PawnIO au premier appel (un seul essai par session). Une
        exception (pilote pas prêt, pas de réponse...) donne NO_RESPONSE."""
        if self._state is None:
            try:
                state = self._open()
            except Exception:
                debug_exc("PawnIO (ouverture)")
                self._failure = self.NO_RESPONSE
                state = False
            self._state = state
        return self._state is True

    def failure_reason(self):
        """Cause de l'échec de l'ouverture, ou None (ouvert, pas encore essayé,
        ou pas demandé). La fenêtre ne fait que traduire la cause en message."""
        return self._failure if self._state is False else None

    def tried(self):
        """True une fois la première ouverture tentée (réussie ou non), sa
        première lecture comprise : le moment où un pilote défaillant ferait
        planter l'appli est passé."""
        return self._state is not None

    def active(self):
        """True si PawnIO est ouvert et lit la température du processeur."""
        return self._state is True

    def owns_cpu_sensor(self):
        """True si PawnIO est la source de la température : l'appelant n'utilise
        alors qu'Afterburner en secours, jamais les replis lents par PowerShell."""
        return self._state is True

    @staticmethod
    def _recent(last):
        """La dernière valeur lue si elle a moins de STALE_S secondes. Un raté
        passager (verrou occupé par HWiNFO...) ne doit pas faire basculer
        l'affichage vers une autre source pour un seul tick."""
        if last and time.monotonic() - last[1] < STALE_S:
            return last[0]
        return None

    def temp(self):
        """Température Tctl/Tdie en °C, ou None."""
        with self._lock:
            return self._temp()

    def _temp(self):
        if not self._ready():
            return None
        locked = False
        try:
            # 0 = obtenu, 0x80 = abandonné par un autre process (obtenu aussi).
            # Attente courte : ce thread mesure aussi GPU, FPS et manettes, et la
            # dernière valeur reste affichée 5 s si le verrou est occupé.
            locked = self._k32.WaitForSingleObject(self._mutex, 10) in (0, 0x80)
            if not locked:
                return self._recent(self._last_temp)
            value = decode_tctl(self._call(b"ioctl_read_smn", SMN_THM_TCON_CUR_TMP), self._offset)
        except Exception:
            debug_exc("PawnIO (temperature)")
            return self._recent(self._last_temp)
        finally:
            if locked:
                self._k32.ReleaseMutex(self._mutex)
        self._last_temp = (value, time.monotonic())
        return value

    def power(self):
        """Consommation du processeur en W (moyenne depuis l'appel précédent), ou None.
        Le tout premier appel ne fait qu'amorcer le compteur."""
        with self._lock:
            return self._power()

    def _power(self):
        if not self._ready() or not self._unit:
            return None
        try:
            counter = self._call(b"ioctl_read_msr", MSR_PKG_ENERGY_STAT) & 0xFFFFFFFF
        except Exception:
            debug_exc("PawnIO (consommation)")
            return self._recent(self._last_power)
        now = time.perf_counter()
        previous, self._energy = self._energy, (counter, now)
        if previous is None:
            return None
        if now - previous[1] > MAX_ENERGY_GAP_S:
            # Longue pause (veille, thread bloqué) : le compteur 32 bits a pu
            # faire plusieurs tours, la moyenne serait fausse mais crédible.
            return self._recent(self._last_power)
        watts = energy_watts(previous[0], counter, self._unit, now - previous[1])
        if watts is None or not 0 <= watts < 1000:
            return self._recent(self._last_power)
        self._last_power = (watts, time.monotonic())
        return watts


# Instance partagée, comme AB pour Afterburner.
PAWNIO = PawnIoCpu()
