"""CachyMonitor : module winshm (voir cachymonitor.py)."""

import time

from .config import AB_SHARED_MEMORY, IS_WINDOWS
from .debug import debug_exc



# ----------------------------------------------------------------------------- #
#  Windows — mémoire partagée
# ----------------------------------------------------------------------------- #
#
# Sous Windows il n'existe pas d'équivalent de /sys : les températures et la
# conso ne sont pas lisibles sans pilote. On lit donc les capteurs déjà publiés
# par MSI Afterburner, que le joueur fait tourner de toute façon pour RivaTuner.
# Avantage décisif pour le FPS : c'est la source de l'OSD RTSS, donc l'appli
# affiche exactement le même chiffre que celui vu en jeu.


SHM_HEADER_SIZE = 64        # en-tête commun aux structures d'Afterburner et de RTSS

_k32_cache = None


def _kernel32():
    """kernel32 avec les signatures nécessaires au 64-bit.

    Sans restype/argtypes explicites, ctypes tronque les pointeurs renvoyés par
    MapViewOfFile à 32 bits et le processus meurt en ACCESS_VIOLATION.

    Les signatures ne changent jamais : on les pose une seule fois, alors que la
    mémoire partagée est relue jusqu'à dix fois par seconde.
    """
    global _k32_cache
    if _k32_cache is None:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.OpenFileMappingW.restype = ctypes.c_void_p
        k32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_bool,
                                         ctypes.c_wchar_p]
        k32.MapViewOfFile.restype = ctypes.c_void_p
        k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                      ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.c_size_t]
        k32.UnmapViewOfFile.restype = ctypes.c_bool
        k32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.restype = ctypes.c_bool
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        _k32_cache = k32
    return _k32_cache


def _read_shared_memory(names, size_from_header):
    """Lit une mémoire partagée Windows nommée, et renvoie ses octets.

    La taille utile n'est connue qu'après lecture de l'en-tête : `size_from_header`
    reçoit les SHM_HEADER_SIZE premiers octets et renvoie le nombre d'octets à
    copier, ou None pour abandonner (signature inconnue, en-tête aberrant).

    Les octets renvoyés commencent à l'en-tête : l'appelant peut le relire depuis
    le début du résultat, sans qu'on ait à le lui repasser séparément.
    """
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        FILE_MAP_READ = 0x0004
        k32 = _kernel32()

        handle = None
        for name in names:
            handle = k32.OpenFileMappingW(FILE_MAP_READ, False, name)
            if handle:
                break
        if not handle:
            return None
        try:
            # Une taille nulle demande la section entière : un seul mapping suffit
            # donc pour lire l'en-tête puis les données qu'il décrit.
            ptr = k32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 0)
            if not ptr:
                return None
            try:
                header = bytes(ctypes.string_at(ptr, SHM_HEADER_SIZE))
                total = size_from_header(header)
                return bytes(ctypes.string_at(ptr, total)) if total else None
            finally:
                k32.UnmapViewOfFile(ptr)
        finally:
            k32.CloseHandle(handle)
    except Exception:
        debug_exc("memoire partagee")
        return None


class AfterburnerReader:
    """Capteurs MSI Afterburner (mémoire partagée « MAHMSharedMemory »).

    Structure MAHM_SHARED_MEMORY :
      en-tête : dwSignature('MAHM') dwVersion dwHeaderSize dwNumEntries dwEntrySize
      entrée  : szSrcName[260] szSrcUnits[260] szLocalizedSrcName[260]
                szLocalizedSrcUnits[260] szRecommendedFormat[260] float data …
    """

    SIGNATURE = 0x4D41484D          # 'MAHM'
    NAME_LEN = 260
    DATA_OFF = NAME_LEN * 5         # le float 'data' suit les cinq chaînes
    NA = 1e30                       # capteur inactif = FLT_MAX, pas 0

    def __init__(self):
        self._cache = {}
        self._cache_time = 0.0

    def read(self):
        """{nom_capteur: valeur}. Caché brièvement : plusieurs lecteurs
        l'interrogent au même tick (CPU, GPU, FPS)."""
        if time.monotonic() - self._cache_time < 0.4:
            return self._cache
        self._cache = self._read_sensors()
        self._cache_time = time.monotonic()
        return self._cache

    def available(self):
        """True si Afterburner tourne et publie ses capteurs."""
        return bool(self.read())

    def get(self, *names):
        """Première valeur exploitable parmi plusieurs noms de capteurs."""
        sensors = self.read()
        for name in names:
            value = sensors.get(name)
            if value is not None:
                return value
        return None

    def _read_sensors(self):
        import struct

        def total_size(header):
            sig, _ver, hdr_sz, count, entry_sz = struct.unpack_from("<IIIII", header, 0)
            if (sig != self.SIGNATURE or hdr_sz > 4096
                    or not 0 < count <= 1024
                    or not self.DATA_OFF + 4 <= entry_sz <= 65536):
                return None
            return hdr_sz + count * entry_sz

        data = _read_shared_memory(AB_SHARED_MEMORY, total_size)
        if not data:
            return {}

        _sig, _ver, hdr_sz, count, entry_sz = struct.unpack_from("<IIIII", data, 0)
        sensors = {}
        for i in range(count):
            base = hdr_sz + i * entry_sz
            if base + entry_sz > len(data):
                break
            name = data[base:base + self.NAME_LEN].split(b"\0")[0]
            if not name:
                continue
            value = struct.unpack_from("<f", data, base + self.DATA_OFF)[0]
            if value != value or abs(value) >= self.NA:   # NaN ou FLT_MAX
                continue
            sensors[name.decode("latin-1")] = value
        return sensors


# Instance partagée : CPU, GPU et FPS viennent tous de la même lecture.
AB = AfterburnerReader()
