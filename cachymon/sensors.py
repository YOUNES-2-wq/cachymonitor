"""CachyMonitor : module sensors (voir cachymonitor.py)."""

import os
import re
import shutil
import time
import subprocess

from .config import _NO_WINDOW, _num, _powershell, plausible_temp
from .debug import debug_exc
from .i18n import tr
from .pawnio import PAWNIO, cpu_registry
from .winshm import AB



# ----------------------------------------------------------------------------- #
#  Lecture des capteurs
# ----------------------------------------------------------------------------- #

def _temp_from_libre_hardware_monitor():
    """Température CPU via le serveur web de LibreHardwareMonitor (port 8085).

    À activer dans LHWM : View > Options > Remote Web Server.
    """
    try:
        import urllib.request
        import json
        with urllib.request.urlopen("http://localhost:8085/data.json",
                                    timeout=1) as resp:
            tree = json.loads(resp.read())
    except Exception:
        debug_exc("LibreHardwareMonitor")
        return None

    def find_temp(node):
        label = node.get("Text", "").lower()
        value = node.get("Value", "")
        if "°c" in value.lower() and any(
            k in label for k in ("cpu package", "core (max)", "tdie",
                                 "tctl", "cpu core", "core max")
        ):
            found = plausible_temp(_num(value.split("°")[0].strip().replace(",", ".")))
            if found is not None:
                return found
        for child in node.get("Children", []):
            found = find_temp(child)
            if found is not None:
                return found
        return None

    return find_temp(tree)


def _temp_from_wmi_sensor(namespace):
    """Température CPU via le fournisseur WMI de LibreHardwareMonitor / OpenHardwareMonitor.

    À activer dans LHWM : View > Options > WMI Server.
    """
    return plausible_temp(_num(_powershell(
        f"Get-WmiObject -Namespace '{namespace}' -Class Sensor "
        "-ErrorAction SilentlyContinue | "
        "Where-Object {$_.SensorType -eq 'Temperature' -and "
        "$_.Name -match 'CPU Package|Core .Max.'} | "
        "Sort-Object Value -Descending | "
        "Select-Object -First 1 -ExpandProperty Value"
    )))


def _temp_from_acpi():
    """Température via la zone thermique ACPI. Souvent réservée à l'administrateur,
    et mesurée à côté du CPU plutôt que dessus : c'est le dernier recours."""
    raw = _num(_powershell(
        "(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi "
        "-ErrorAction SilentlyContinue | Sort-Object CurrentTemperature "
        "-Descending | Select-Object -First 1).CurrentTemperature"
    ))
    # MSAcpi rend des dixièmes de kelvin.
    return plausible_temp(raw / 10.0 - 273.15) if raw is not None else None


class _PdhCpuFreq:
    """Fréquence CPU réelle via les compteurs de performance Windows (PDH).

    C'est le calcul du Gestionnaire des tâches : fréquence de base × « % de
    performance du processeur » / 100, ce pourcentage dépassant 100 en boost.
    Aucun droit admin ni pilote requis. Les noms de compteurs sont traduits
    selon la langue de Windows : PdhAddEnglishCounterW accepte les noms
    anglais quelle que soit la langue.

    Le pourcentage est une moyenne entre deux relevés : le tout premier appel
    ne donne rien, l'appelant garde alors sa source de secours.
    """

    PDH_FMT_DOUBLE = 0x00000200
    PDH_FMT_NOCAP100 = 0x00008000   # sans lui, le boost serait plafonné à 100 %
    PERF = r"\Processor Information(_Total)\% Processor Performance"
    BASE = r"\Processor Information(_Total)\Processor Frequency"

    def __init__(self):
        self._pdh = None        # None = pas encore essayé, False = indisponible
        self._query = self._perf = self._base = None

    def _open(self):
        import ctypes
        H = ctypes.c_void_p
        try:
            pdh = ctypes.WinDLL("pdh.dll")
        except OSError:
            return False

        class Fmt(ctypes.Structure):
            # Le second champ est une union (LONG / double / ...) alignée sur
            # 8 octets ; seul le double nous intéresse.
            _fields_ = [("CStatus", ctypes.c_ulong), ("doubleValue", ctypes.c_double)]

        # Types déclarés partout : sans eux ctypes tronque les handles 64 bits
        # (bug n°3, le crash ACCESS_VIOLATION).
        pdh.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(H)]
        pdh.PdhAddEnglishCounterW.argtypes = [H, ctypes.c_wchar_p, ctypes.c_size_t,
                                              ctypes.POINTER(H)]
        pdh.PdhCollectQueryData.argtypes = [H]
        pdh.PdhGetFormattedCounterValue.argtypes = [H, ctypes.c_ulong, ctypes.c_void_p,
                                                    ctypes.POINTER(Fmt)]
        for f in (pdh.PdhOpenQueryW, pdh.PdhAddEnglishCounterW,
                  pdh.PdhCollectQueryData, pdh.PdhGetFormattedCounterValue):
            f.restype = ctypes.c_long

        query, perf, base = H(), H(), H()
        if pdh.PdhOpenQueryW(None, 0, ctypes.byref(query)) != 0:
            return False
        if (pdh.PdhAddEnglishCounterW(query, self.PERF, 0, ctypes.byref(perf)) != 0
                or pdh.PdhAddEnglishCounterW(query, self.BASE, 0, ctypes.byref(base)) != 0):
            return False
        pdh.PdhCollectQueryData(query)     # premier relevé, la référence
        self._fmt = Fmt
        self._query, self._perf, self._base = query, perf, base
        return pdh

    def _value(self, counter):
        import ctypes
        out = self._fmt()
        rc = self._pdh.PdhGetFormattedCounterValue(
            counter, self.PDH_FMT_DOUBLE | self.PDH_FMT_NOCAP100, None, ctypes.byref(out))
        return out.doubleValue if rc == 0 else None

    def mhz(self):
        if self._pdh is None:
            try:
                self._pdh = self._open()
            except Exception:
                debug_exc("frequence CPU (PDH)")
                self._pdh = False
        if not self._pdh:
            return None
        if self._pdh.PdhCollectQueryData(self._query) != 0:
            return None
        perf, base = self._value(self._perf), self._value(self._base)
        if not perf or not base:
            return None
        freq = base * perf / 100.0
        return freq if 100 < freq < 10000 else None


class WindowsCpuReader:
    """Usage CPU (total + par cœur) via psutil, températures via PawnIO.

    Windows n'expose pas de capteur thermique lisible sans pilote : la
    température et la consommation viennent du pilote PawnIO (Ryzen, droits
    administrateur), sinon de MSI Afterburner, avec des sources de repli
    quand il n'est pas lancé. La fréquence réelle vient des
    compteurs Windows (_PdhCpuFreq), Afterburner en secours.
    """

    # Sources de repli, dans l'ordre de préférence. Toutes passent par HTTP ou
    # PowerShell : trop lentes pour chaque tick, d'où le cache.
    TEMP_FALLBACKS = (
        _temp_from_libre_hardware_monitor,
        lambda: _temp_from_wmi_sensor("root/LibreHardwareMonitor"),
        lambda: _temp_from_wmi_sensor("root/OpenHardwareMonitor"),
        _temp_from_acpi,
    )
    FALLBACK_CACHE_S = 5.0

    def __init__(self):
        # psutil.cpu_percent() compare deux appels : le premier amorce le
        # compteur, sinon le tout premier échantillon vaudrait 0 %.
        try:
            import psutil
            psutil.cpu_percent(interval=None)
            psutil.cpu_percent(percpu=True, interval=None)
        except ImportError:
            pass
        self._temp_cache = None
        self._temp_cache_time = 0.0
        self._freq = _PdhCpuFreq()

    def _temp(self):
        # PawnIO d'abord (1.7.0) : lu directement dans le processeur, sans
        # logiciel tiers. Il faut les droits administrateur et un Ryzen.
        temp = plausible_temp(PAWNIO.temp())
        if temp is not None:
            return temp
        # PawnIO ne répond plus depuis plus de 5 s (pause passagère couverte par
        # sa dernière valeur) : Afterburner prend le relais plutôt que « — ».
        # Seulement lui, pas les replis lents par PowerShell, ni pendant que
        # PawnIO attend un nouvel essai d'ouverture (pilote pas encore prêt).
        temp = plausible_temp(AB.get("CPU temperature"))
        if PAWNIO.owns_cpu_sensor():
            return temp
        if temp is not None:
            return temp

        if time.time() - self._temp_cache_time < self.FALLBACK_CACHE_S:
            return self._temp_cache

        temp = None
        for source in self.TEMP_FALLBACKS:
            temp = source()
            if temp is not None:
                break
        self._temp_cache = temp
        self._temp_cache_time = time.time()
        return temp

    def sample(self):
        try:
            import psutil
            cpu_pct = psutil.cpu_percent(interval=None)
            cpu_cores = psutil.cpu_percent(percpu=True, interval=None)
            freq = psutil.cpu_freq()
            cpu_freq = freq.current if freq else None
        except ImportError:
            cpu_pct, cpu_cores, cpu_freq = 0.0, [], None

        # psutil lit la fréquence *de base* dans le registre, une valeur figée.
        # La fréquence réelle, boost compris, vient des compteurs Windows, ou à
        # défaut d'Afterburner.
        real = self._freq.mhz()
        if real is None:
            boost = AB.get("CPU clock")
            if boost and 100 < boost < 10000:
                real = boost
        if real is not None:
            cpu_freq = real

        return {
            "cpu_pct": cpu_pct,
            "cpu_cores": cpu_cores,
            "cpu_freq": cpu_freq,
            "cpu_temp": self._temp(),
            "cpu_power": self._power(),
        }

    @staticmethod
    def _power():
        # Même règle que la température : PawnIO tant qu'il répond (un raté
        # passager est couvert par sa dernière valeur pendant 5 s), sinon
        # Afterburner. Seul le tout premier relevé, qui amorce le compteur
        # d'énergie de PawnIO, vient d'Afterburner.
        watts = PAWNIO.power()
        return watts if watts is not None else AB.get("CPU power")


def make_cpu_reader():
    """Lecteur CPU de la plateforme."""
    return WindowsCpuReader()


def read_ram():
    try:
        import psutil
        mem = psutil.virtual_memory()
    except ImportError:
        return {"ram_used": 0.0, "ram_total": 0.0, "ram_pct": 0.0}
    gib = 1024 ** 3
    return {
        "ram_used": mem.used / gib,
        "ram_total": mem.total / gib,
        "ram_pct": mem.percent,
    }


# ----------------------------------------------------------------------------- #
#  Détection du nom du matériel (statique : lu une seule fois au démarrage)
# ----------------------------------------------------------------------------- #

def _clean_cpu(name):
    """Raccourcit le libellé CPU : 'AMD Ryzen 5 5600 6-Core Processor' -> 'AMD Ryzen 5 5600'."""
    name = re.sub(r"\(R\)|\(TM\)|\(tm\)", "", name)
    name = re.sub(r"\s*\d+-Core Processor", "", name)
    name = re.sub(r"@.*$", "", name)
    name = name.replace("Processor", "").replace("CPU", "")
    return " ".join(name.split()) or "CPU"


def read_cpu_name():
    """Nom du processeur (ex: 'AMD Ryzen 5 5600')."""
    # Le registre répond instantanément, contrairement à WMI — et wmic a été
    # retiré de Windows 11 24H2.
    name = cpu_registry("ProcessorNameString")    # toujours du texte (_hklm)
    return _clean_cpu(name) if name else "CPU"


# Codes SMBIOS des types de mémoire, tels que Win32_PhysicalMemory les rapporte.
SMBIOS_MEMORY_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4",
                       34: "DDR5", 35: "LPDDR4", 37: "LPDDR5"}


def _ram_cim():
    """Type + vitesse RAM via CIM (Windows), ex: 'DDR4 3200 MT/s'."""
    out = _powershell(
        "Get-CimInstance Win32_PhysicalMemory -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 | ForEach-Object "
        "{ \"$($_.SMBIOSMemoryType) $($_.Speed)\" }",
        timeout=6,
    ).split()
    if len(out) < 2:
        return None
    mtype = SMBIOS_MEMORY_TYPES.get(int(_num(out[0]) or 0))
    speed = _num(out[1])
    parts = [mtype, f"{speed:.0f} MT/s" if speed else None]
    return " ".join(p for p in parts if p) or None


# CIM coûte cher : la RAM ne change pas en cours de session, on
# ne l'interroge donc qu'une fois (read_ram_name est rappelé à chaque
# changement de langue, pour traduire l'unité).
_RAM_EXTRA_UNREAD = object()
_ram_extra_cache = _RAM_EXTRA_UNREAD


def _ram_extra():
    global _ram_extra_cache
    if _ram_extra_cache is _RAM_EXTRA_UNREAD:
        try:
            _ram_extra_cache = _ram_cim()
        except Exception:
            debug_exc("RAM (type, vitesse)")
            _ram_extra_cache = None
    return _ram_extra_cache


def read_ram_name():
    """Capacité physique (+ type/vitesse si lisibles), ex: '16 Gio · DDR4 3200 MT/s'."""
    kb = None
    try:
        import psutil
        kb = psutil.virtual_memory().total / 1024
    except ImportError:
        pass
    if not kb:
        return "RAM"
    gib = kb / 1024 / 1024
    # La capacité « affichée » est < à la capacité physique (kernel, intégré) :
    # on arrondit au multiple de 4 Gio le plus proche pour retomber sur 8/16/32…
    phys = round(gib / 4) * 4 if gib > 6 else round(gib)
    cap = f"{phys} {tr('GiB')}"
    extra = _ram_extra()
    return f"{cap} · {extra}" if extra else cap


_nvidia_smi_path = None


def _nvidia_smi():
    """Chemin de nvidia-smi, qui n'est pas toujours dans le PATH.

    Résolu une seule fois : read_gpu() est appelé à chaque tick, et parcourir le
    PATH toutes les secondes pour une réponse invariable ne sert à rien.
    """
    global _nvidia_smi_path
    if _nvidia_smi_path is None:
        _nvidia_smi_path = "nvidia-smi"
        fallback = r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
        if not shutil.which("nvidia-smi") and os.path.exists(fallback):
            _nvidia_smi_path = fallback
    return _nvidia_smi_path


_nvml_lib = None   # None = pas encore essayé, False = indisponible
_nvml_handle = None


def _nvml_paths():
    """Emplacements de la bibliothèque NVML, dans l'ordre d'essai.

    On donne un chemin complet : avec un simple « nvml.dll », Windows chercherait
    d'abord dans le dossier courant, où un fichier piégé pourrait se faire passer
    pour la vraie bibliothèque. Le pilote NVIDIA installe nvml.dll dans System32 ;
    les anciens pilotes la mettaient dans NVSMI.
    """
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return [os.path.join(root, "System32", "nvml.dll"),
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll"]


def _nvml_open():
    """Charge NVML une seule fois.

    C'est la source principale : un appel direct au pilote, sans lancer
    nvidia-smi à chaque seconde.
    """
    global _nvml_lib, _nvml_handle
    if _nvml_lib is not None:
        return _nvml_lib or None
    _nvml_lib = False
    import ctypes
    for path in _nvml_paths():
        if not os.path.exists(path):
            continue
        try:
            lib = ctypes.CDLL(path)
            break
        except OSError:
            continue
    else:
        return None
    try:
        if lib.nvmlInit_v2() != 0:
            return None
        handle = ctypes.c_void_p()
        if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
            return None
    except (OSError, AttributeError):
        return None
    _nvml_lib, _nvml_handle = lib, handle
    return lib


def _gpu_nvidia_nvml():
    """GPU NVIDIA via NVML, mêmes champs que _gpu_nvidia()."""
    lib = _nvml_open()
    if lib is None:
        return None
    import ctypes

    class Util(ctypes.Structure):
        _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

    class Mem(ctypes.Structure):
        _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong),
                    ("used", ctypes.c_ulonglong)]

    class Mem2(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint), ("total", ctypes.c_ulonglong),
                    ("reserved", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong),
                    ("used", ctypes.c_ulonglong)]

    h = _nvml_handle
    name = ctypes.create_string_buffer(96)
    util = Util()
    temp, clock, power = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
    if lib.nvmlDeviceGetName(h, name, 96) != 0:
        return None
    ok_util = lib.nvmlDeviceGetUtilizationRates(h, ctypes.byref(util)) == 0
    # La version 2 retire de « used » la mémoire réservée par le pilote, comme
    # nvidia-smi (1604 Mio contre 1777 sur une RTX 3060). Les pilotes trop
    # anciens ne l'ont pas : on retombe alors sur la version 1.
    mem = Mem2()
    mem.version = ctypes.sizeof(Mem2) | (2 << 24)
    try:
        ok_mem = lib.nvmlDeviceGetMemoryInfo_v2(h, ctypes.byref(mem)) == 0
    except AttributeError:
        ok_mem = False
    if not ok_mem:
        mem = Mem()
        ok_mem = lib.nvmlDeviceGetMemoryInfo(h, ctypes.byref(mem)) == 0
    ok_temp = lib.nvmlDeviceGetTemperature(h, 0, ctypes.byref(temp)) == 0  # 0 = cœur GPU
    ok_clock = lib.nvmlDeviceGetClockInfo(h, 0, ctypes.byref(clock)) == 0  # 0 = graphique
    ok_power = lib.nvmlDeviceGetPowerUsage(h, ctypes.byref(power)) == 0    # milliwatts
    return {
        "gpu_name": name.value.decode(errors="replace"),
        "gpu_pct": float(util.gpu) if ok_util else 0.0,
        "gpu_temp": float(temp.value) if ok_temp else None,
        "vram_used": mem.used / 1048576 if ok_mem else 0.0,   # MiB
        "vram_total": mem.total / 1048576 if ok_mem else 0.0,
        "gpu_clock": float(clock.value) if ok_clock else None,
        "gpu_power": power.value / 1000 if ok_power else None,
    }


def _gpu_nvidia():
    """GPU NVIDIA (usage, temp, VRAM, clock, power).

    NVML d'abord, nvidia-smi en secours.
    """
    data = _gpu_nvidia_nvml()
    if data:
        return data
    query = "name,utilization.gpu,temperature.gpu,memory.used,memory.total,clocks.gr,power.draw"
    try:
        out = subprocess.run(
            [_nvidia_smi(), f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4, **_NO_WINDOW,
        ).stdout.strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    fields = [x.strip() for x in out[0].split(",")]
    if len(fields) < 7:
        return None
    return {
        "gpu_name": fields[0],
        "gpu_pct": _num(fields[1]) or 0.0,
        "gpu_temp": _num(fields[2]),
        "vram_used": _num(fields[3]) or 0.0,   # MiB
        "vram_total": _num(fields[4]) or 0.0,
        "gpu_clock": _num(fields[5]),
        "gpu_power": _num(fields[6]),
    }


def _gpu_afterburner():
    """GPU via les capteurs Afterburner (cartes non-NVIDIA).

    Windows n'expose pas directement les capteurs d'une Radeon ou d'un iGPU
    Intel : Afterburner, lui, sait les lire. Le nom commercial ne fait pas
    partie des capteurs, d'où le libellé générique.

    ⚠️ NON TESTÉ sur du matériel AMD/Intel. Retours bienvenus.
    """
    usage = AB.get("GPU usage")
    temp = AB.get("GPU temperature")
    if usage is None and temp is None:
        return None
    return {
        "gpu_name": "GPU",
        "gpu_pct": usage or 0.0,
        "gpu_temp": temp,
        "vram_used": AB.get("Memory usage") or 0.0,   # Mio
        "vram_total": 0.0,                            # non exposé par Afterburner
        "gpu_clock": AB.get("Core clock"),
        "gpu_power": AB.get("Power"),
    }


def read_gpu():
    """Lit le GPU, quel que soit le constructeur.

    On essaie NVIDIA (NVML, puis nvidia-smi), puis les capteurs Afterburner
    pour les autres cartes. Le premier lecteur qui renvoie quelque chose
    gagne ; si aucun ne répond, l'interface affiche « GPU indisponible » au lieu
    de planter.
    """
    for reader in (_gpu_nvidia, _gpu_afterburner):
        try:
            data = reader()
        except Exception:
            debug_exc("GPU : " + reader.__name__)
            data = None          # un GPU exotique ne doit jamais faire tomber l'app
        if data:
            return data
    return _gpu_none()


def _gpu_none():
    return {
        "gpu_name": tr("GPU unavailable"), "gpu_pct": 0.0, "gpu_temp": None,
        "vram_used": 0.0, "vram_total": 0.0, "gpu_clock": None, "gpu_power": None,
    }
