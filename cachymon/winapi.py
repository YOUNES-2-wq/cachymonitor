"""Liaisons Win32 (ctypes) et lecture du registre partagées par pawnio.py,
elevation.py et debug.py. Aucune règle de sécurité ici : seulement les appels
Windows, leurs types (bug n°3 : sans types, ctypes tronque les handles 64 bits)
et un petit cache. Ce module n'importe rien du reste de l'appli."""

import contextlib
import ctypes
import functools


@functools.lru_cache(maxsize=1)
def kernel32_api():
    """kernel32 avec les types de toutes les fonctions utilisées, déclarés une
    seule fois (bug n°3 : sans types, ctypes tronque les handles 64 bits).
    Seule liaison kernel32 de pawnio.py et elevation.py."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    k32.OpenMutexW.restype = ctypes.c_void_p
    k32.OpenMutexW.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_wchar_p]
    k32.WaitForSingleObject.restype = ctypes.c_ulong
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    k32.ReleaseMutex.argtypes = [ctypes.c_void_p]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.LocalFree.restype = ctypes.c_void_p
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.GetCurrentProcessId.restype = ctypes.c_ulong
    for f in (k32.GetSystemWindowsDirectoryW, k32.GetSystemDirectoryW):
        f.restype = ctypes.c_uint
        f.argtypes = [ctypes.c_wchar_p, ctypes.c_uint]
    return k32


class SecurityAttributes(ctypes.Structure):
    """SECURITY_ATTRIBUTES (verrou nommé ouvert à tous)."""
    _fields_ = [("nLength", ctypes.c_ulong), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", ctypes.c_int)]


def create_mutex(name, shared=False):
    """(handle, déjà_existant) pour un verrou nommé. handle None si Windows
    refuse (droits plus stricts d'un autre créateur, nom pris par autre chose).
    shared : verrou créé ouvert à tous les comptes (accès complet à « Tout le
    monde »), pour un verrou commun à plusieurs outils, comme Global\\Access_PCI :
    sans cela, créé par un process administrateur, il serait fermé aux autres.
    Seul appel à CreateMutexW de l'appli : même règle partout."""
    k32 = kernel32_api()
    attributes, descriptor = None, ctypes.c_void_p()
    if shared:
        advapi32 = advapi32_api()
        if advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                "D:(A;;GA;;;WD)", 1, ctypes.byref(descriptor), None):
            sa = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, 0)
            attributes = ctypes.addressof(sa)
    ctypes.set_last_error(0)
    try:
        handle = k32.CreateMutexW(attributes, False, name)
        existed = ctypes.get_last_error() == 183      # ERROR_ALREADY_EXISTS
    finally:
        if descriptor.value:
            k32.LocalFree(descriptor)
    return (handle or None), existed


class ShellExecuteInfo(ctypes.Structure):
    """SHELLEXECUTEINFOW (relance par ShellExecuteExW, elevation.py)."""
    _fields_ = [("cbSize", ctypes.c_ulong), ("fMask", ctypes.c_ulong),
                ("hwnd", ctypes.c_void_p), ("lpVerb", ctypes.c_wchar_p),
                ("lpFile", ctypes.c_wchar_p), ("lpParameters", ctypes.c_wchar_p),
                ("lpDirectory", ctypes.c_wchar_p), ("nShow", ctypes.c_int),
                ("hInstApp", ctypes.c_void_p), ("lpIDList", ctypes.c_void_p),
                ("lpClass", ctypes.c_wchar_p), ("hkeyClass", ctypes.c_void_p),
                ("dwHotKey", ctypes.c_ulong), ("hIconOrMonitor", ctypes.c_void_p),
                ("hProcess", ctypes.c_void_p)]


@functools.lru_cache(maxsize=1)
def shell32_api():
    """shell32 avec ses types, déclarés une seule fois (bug n°3)."""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.IsUserAnAdmin.restype = ctypes.c_int
    shell32.IsUserAnAdmin.argtypes = []
    shell32.ShellExecuteExW.restype = ctypes.c_int
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    return shell32


@functools.lru_cache(maxsize=1)
def advapi32_api():
    """advapi32 avec ses types, déclarés une seule fois (bug n°3), comme kernel32_api()."""
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.HANDLE)]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = ctypes.c_int
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                             wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    return advapi32


@contextlib.contextmanager
def process_token():
    """Jeton du process courant (lecture seule), refermé à la sortie du bloc."""
    from ctypes import wintypes
    advapi32 = advapi32_api()
    kernel32 = kernel32_api()
    TOKEN_QUERY = 0x0008
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY,
                                     ctypes.byref(token)):
        raise OSError("OpenProcessToken (erreur %d)" % ctypes.get_last_error())
    try:
        yield token
    finally:
        kernel32.CloseHandle(token)


def cache_final(func):
    """Cache d'une fonction sans argument qui rend (valeur, définitive) : la
    valeur n'est gardée que si elle est définitive ; sinon (échec passager) elle
    est rendue mais recalculée à l'appel suivant. cache_clear() comme
    functools.lru_cache."""
    cell = []

    @functools.wraps(func)
    def wrapper():
        if cell:
            return cell[0]
        value, final = func()
        if final:
            cell.append(value)
        return value
    wrapper.cache_clear = cell.clear
    return wrapper


def cache_known(func):
    """Garde en cache le premier résultat différent de None (une valeur lue
    pour de bon) ; None = échec passager, réessayé à l'appel suivant."""
    @functools.wraps(func)
    def known():
        value = func()
        return value, value is not None
    return cache_final(known)


def hklm(subkey, value):
    """Valeur texte de HKLM (vue 64 bits), ou "". HKLM n'est modifiable que par un
    administrateur, contrairement aux variables d'environnement, qu'un programme
    ordinaire peut redéfinir pour l'utilisateur (HKCU\\Environment)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return str(winreg.QueryValueEx(key, value)[0])
    except (OSError, ImportError):
        return ""
