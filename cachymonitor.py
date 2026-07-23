#!/usr/bin/env python3
"""
CachyMonitor — moniteur système pour CachyOS (CPU / GPU / RAM / températures / FPS).

Dépendance unique : PySide6 (pacman -S pyside6).
Tout est lu depuis /proc, /sys (hwmon), nvidia-smi et les logs MangoHud.
Aucune autre librairie : les graphes sont dessinés au QPainter.
"""

import os
import re
import sys
import glob
import time
import subprocess
from collections import deque

from PySide6.QtCore import Qt, QThread, Signal, QPointF, QRectF, QSettings
from PySide6.QtGui import (
    QPainter, QColor, QPainterPath, QPen, QBrush, QFont, QLinearGradient, QIcon,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
    QCheckBox, QSpinBox, QSizePolicy,
)

IS_WINDOWS = sys.platform.startswith("win")

# ----------------------------------------------------------------------------- #
#  Configuration
# ----------------------------------------------------------------------------- #

HISTORY = 120          # nombre d'échantillons gardés pour les graphes
GAME_HISTORY = 6000    # échantillons MangoHud gardés (100 ms => ~10 min de jeu)
LOG_INTERVAL_MS = 100  # log_interval de MangoHud (repli si 'elapsed' absent du CSV)
GAME_WARMUP_S = 5.0    # début de session ignoré (lancement + 1er chargement)
GAME_WINDOW_S = 60.0   # fenêtre glissante sur laquelle les « lows » sont calculés
# Une image qui dure plus d'une seconde n'est pas une saccade de jeu : c'est le
# jeu suspendu (alt-tab, pause, chargement). On l'écarte des statistiques, sinon
# elle écrase à elle seule le 0.1% low. Seuil volontairement très conservateur :
# une vraie saccade ressentie reste bien au-dessus de 1 fps.
FREEZE_IGNORE_MS = 1000.0
DEFAULT_INTERVAL_MS = 1000
DEFAULT_FPS_TARGET = 165   # sert d'échelle aux jauges FPS (= fps_limit MangoHud)

# Dossiers où chercher les logs CSV de MangoHud (le plus récent est utilisé).
FPS_LOG_DIRS = [
    os.path.expanduser("~/.local/share/MangoHud/logs"),
    os.path.expanduser("~/mangohud"),
    os.path.expanduser("~/.local/share/MangoHud"),
    os.path.expanduser("~/.local/share/goverlay"),  # output_folder par défaut de Goverlay
    os.path.expanduser("~/.local/share/goverlay/logs"),
    os.getcwd(),
]
FPS_STALE_SECONDS = 5  # au-delà, on considère qu'aucun jeu ne tourne

# Couleurs d'accent par métrique
C_CPU = "#4ca3ff"
C_GPU = "#5ddc7f"
C_RAM = "#b48cff"
C_VRAM = "#ff9d5c"
C_FPS = "#ffd23f"
C_FT = "#ff6b8a"       # frametime (les pics = micro-saccades)
C_OK = "#5ddc7f"
C_WARN = "#ffb347"
C_BAD = "#ff5f56"
C_BG = "#13151b"
C_CARD = "#1c1f29"
C_TEXT = "#e6e9f0"
C_MUTED = "#7d8499"


def temp_color(t):
    if t is None:
        return C_MUTED
    if t >= 85:
        return "#ff5c5c"
    if t >= 70:
        return "#ff9d5c"
    return "#5ddc7f"


# ----------------------------------------------------------------------------- #
#  Lecture des capteurs
# ----------------------------------------------------------------------------- #

def _find_hwmon(name):
    """Renvoie le chemin d'un hwmon par son nom (ex: 'k10temp')."""
    if IS_WINDOWS:
        return None
    for path in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            with open(os.path.join(path, "name")) as f:
                if f.read().strip() == name:
                    return path
        except OSError:
            continue
    return None


class CpuReader:
    """Usage CPU (total + par cœur), fréquence et température."""

    def __init__(self):
        if IS_WINDOWS:
            try:
                import psutil
                psutil.cpu_percent(interval=None)
                psutil.cpu_percent(percpu=True, interval=None)
            except ImportError:
                pass
        else:
            self._prev = self._read_stat()
            self._k10 = _find_hwmon("k10temp")
            # Sur k10temp, Tctl est généralement temp1_input.
            self._temp_file = None
            if self._k10:
                cand = os.path.join(self._k10, "temp1_input")
                if os.path.exists(cand):
                    self._temp_file = cand

    @staticmethod
    def _read_stat():
        totals = {}
        with open("/proc/stat") as f:
            for line in f:
                if not line.startswith("cpu"):
                    break
                parts = line.split()
                key = parts[0]
                vals = list(map(int, parts[1:]))
                idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
                total = sum(vals)
                totals[key] = (idle, total)
        return totals

    def _usage(self):
        cur = self._read_stat()
        out = {}
        for key, (idle, total) in cur.items():
            pidle, ptotal = self._prev.get(key, (idle, total))
            dt = total - ptotal
            di = idle - pidle
            out[key] = max(0.0, min(100.0, 100.0 * (1 - di / dt))) if dt > 0 else 0.0
        self._prev = cur
        return out

    @staticmethod
    def _freq_mhz():
        files = glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")
        vals = []
        for fp in files:
            try:
                with open(fp) as f:
                    vals.append(int(f.read()) / 1000.0)  # kHz -> MHz
            except (OSError, ValueError):
                pass
        return sum(vals) / len(vals) if vals else None

    def _temp(self):
        if not self._temp_file:
            return None
        try:
            with open(self._temp_file) as f:
                return int(f.read()) / 1000.0
        except (OSError, ValueError):
            return None

    def sample_win(self):
        try:
            import psutil
            cpu_pct = psutil.cpu_percent(interval=None)
            cpu_cores = psutil.cpu_percent(percpu=True, interval=None)
            freq_info = psutil.cpu_freq()
            cpu_freq = freq_info.current if freq_info else None
        except ImportError:
            return {
                "cpu_pct": 0.0,
                "cpu_cores": [],
                "cpu_freq": None,
                "cpu_temp": None,
            }

        # Température via WMI
        cpu_temp = None
        try:
            import win32com.client
            wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\wmi")
            for item in wmi.InstancesOf("MSAcpi_ThermalZoneTemperature"):
                cpu_temp = (item.CurrentTemperature / 10.0) - 273.15
                break
        except Exception:
            pass

        return {
            "cpu_pct": cpu_pct,
            "cpu_cores": cpu_cores,
            "cpu_freq": cpu_freq,
            "cpu_temp": cpu_temp,
        }

    def sample(self):
        if IS_WINDOWS:
            return self.sample_win()
        usage = self._usage()
        cores = sorted(
            (k for k in usage if k != "cpu"),
            key=lambda k: int(k[3:]),
        )
        return {
            "cpu_pct": usage.get("cpu", 0.0),
            "cpu_cores": [usage[k] for k in cores],
            "cpu_freq": self._freq_mhz(),
            "cpu_temp": self._temp(),
        }


def read_ram():
    if IS_WINDOWS:
        try:
            import psutil
            mem = psutil.virtual_memory()
            return {
                "ram_used": mem.used / 1024 / 1024 / 1024,
                "ram_total": mem.total / 1024 / 1024 / 1024,
                "ram_pct": mem.percent,
            }
        except ImportError:
            return {"ram_used": 0.0, "ram_total": 0.0, "ram_pct": 0.0}

    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, v = line.partition(":")
            info[k] = int(v.split()[0])  # kB
    total = info.get("MemTotal", 0) / 1024 / 1024          # GiB
    avail = info.get("MemAvailable", 0) / 1024 / 1024
    used = total - avail
    pct = (used / total * 100) if total else 0.0
    return {"ram_used": used, "ram_total": total, "ram_pct": pct}


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
    if IS_WINDOWS:
        try:
            import platform
            return _clean_cpu(platform.processor() or "CPU")
        except Exception:
            return "CPU"
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return _clean_cpu(line.split(":", 1)[1].strip())
    except OSError:
        pass
    return "CPU"


def _ram_dmi():
    """Type + vitesse RAM via dmidecode, uniquement si accessible sans sudo (sinon None)."""
    try:
        out = subprocess.run(
            ["dmidecode", "-t", "memory"],
            capture_output=True, text=True, timeout=2,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    mtype = speed = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Type:") and "DDR" in line:
            mtype = line.split(":", 1)[1].strip()
        elif line.startswith("Configured Memory Speed:") and "Unknown" not in line:
            speed = line.split(":", 1)[1].strip()
    parts = [p for p in (mtype, speed) if p]
    return " ".join(parts) or None


def read_ram_name():
    """Capacité physique (+ type/vitesse si dmidecode dispo), ex: '16 Gio · DDR4 3200 MT/s'."""
    if IS_WINDOWS:
        try:
            import psutil
            gib = psutil.virtual_memory().total / 1024 / 1024 / 1024
        except ImportError:
            return "RAM"
    else:
        kb = None
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        kb = int(line.split()[1])
                        break
        except OSError:
            pass
        if not kb:
            return "RAM"
        gib = kb / 1024 / 1024
    # La capacité « affichée » est < à la capacité physique (kernel, intégré) :
    # on arrondit au multiple de 4 Gio le plus proche pour retomber sur 8/16/32…
    phys = round(gib / 4) * 4 if gib > 6 else round(gib)
    cap = f"{phys} Gio"
    extra = _ram_dmi()
    return f"{cap} · {extra}" if extra else cap


def read_gpu():
    """GPU NVIDIA via nvidia-smi (usage, temp, VRAM, clock, power)."""
    query = "name,utilization.gpu,temperature.gpu,memory.used,memory.total,clocks.gr,power.draw"
    cmd = "nvidia-smi"
    if IS_WINDOWS:
        import shutil
        if not shutil.which("nvidia-smi"):
            cand = r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
            if os.path.exists(cand):
                cmd = cand
    try:
        out = subprocess.run(
            [cmd, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
        ).stdout.strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return _gpu_none()
    if not out:
        return _gpu_none()
    fields = [x.strip() for x in out[0].split(",")]
    if len(fields) < 7:
        return _gpu_none()

    def num(x):
        try:
            return float(x)
        except ValueError:
            return None

    return {
        "gpu_name": fields[0],
        "gpu_pct": num(fields[1]) or 0.0,
        "gpu_temp": num(fields[2]),
        "vram_used": num(fields[3]) or 0.0,   # MiB
        "vram_total": num(fields[4]) or 0.0,
        "gpu_clock": num(fields[5]),
        "gpu_power": num(fields[6]),
    }


def _gpu_none():
    return {
        "gpu_name": "GPU indisponible", "gpu_pct": 0.0, "gpu_temp": None,
        "vram_used": 0.0, "vram_total": 0.0, "gpu_clock": None, "gpu_power": None,
    }


class GameReader:
    """Lit une session de jeu depuis le log CSV MangoHud le plus récent.

    Lecture *incrémentale* (on garde l'offset atteint) pour accumuler les
    échantillons et calculer les métriques qui comptent en jeu : 1% low,
    0.1% low, moyenne et frametimes.

    Deux précautions sur la qualité des données :
      * on ignore les GAME_WARMUP_S premières secondes (lancement du jeu,
        premier chargement : MangoHud y enregistre des images à 0 fps) ;
      * les « lows » sont calculés sur une **fenêtre glissante** des
        GAME_WINDOW_S dernières secondes. Sur une session entière, un écran
        de chargement en milieu de partie plomberait définitivement le
        0.1% low alors qu'il ne dit rien de la fluidité actuelle.
    """

    # Colonnes du CSV MangoHud qui nous intéressent.
    WANTED = ("fps", "frametime", "cpu_load", "gpu_load", "gpu_vram_used",
              "gpu_core_clock", "cpu_temp", "gpu_temp", "elapsed")

    def __init__(self):
        self._path = None        # log en cours de suivi
        self._pos = 0            # offset de lecture déjà consommé
        self._cols = None        # nom de colonne -> index
        # échantillons (t_secondes, fps, frametime_ms)
        self._samples = deque(maxlen=GAME_HISTORY)
        self._n = 0              # compteur, sert de repli si 'elapsed' absent
        self._t0 = None          # 'elapsed' de la 1re ligne (en ns)
        self._last = {}          # dernière ligne complète parsée

    # -- helpers ---------------------------------------------------------- #
    @staticmethod
    def _newest_log():
        newest, newest_mtime = None, 0
        for d in FPS_LOG_DIRS:
            for fp in glob.glob(os.path.join(d, "*.csv")):
                try:
                    m = os.path.getmtime(fp)
                except OSError:
                    continue
                if m > newest_mtime:
                    newest, newest_mtime = fp, m
        return newest, newest_mtime

    @staticmethod
    def _game_name(path):
        """urbanterror_2026-07-20_12-40-15.csv -> Urbanterror"""
        base = os.path.basename(path)
        base = re.sub(r"\.csv$", "", base, flags=re.I)
        base = re.sub(r"_\d{4}-\d{2}-\d{2}[_-]\d{2}-\d{2}-\d{2}$", "", base)
        return base.replace("_", " ").strip().title() or "Jeu"

    def _reset_for(self, path):
        self._path = path
        self._pos = 0
        self._cols = None
        self._samples.clear()
        self._n = 0
        self._t0 = None
        self._last = {}

    def _parse_header(self, line):
        cols = [c.strip().lower() for c in line.split(",")]
        if "fps" not in cols:
            return None
        return {name: cols.index(name) for name in self.WANTED if name in cols}

    def _consume(self, path):
        """Lit les nouvelles lignes depuis la dernière position connue."""
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        # Fichier tronqué / recréé : on repart de zéro.
        if size < self._pos:
            self._reset_for(path)
        try:
            with open(path, "r", errors="ignore") as f:
                f.seek(self._pos)
                chunk = f.read()
                self._pos = f.tell()
        except OSError:
            return

        for line in chunk.splitlines():
            if not line.strip():
                continue
            if self._cols is None:
                self._cols = self._parse_header(line)
                continue
            parts = line.split(",")
            row = {}
            for name, idx in self._cols.items():
                if idx < len(parts):
                    try:
                        row[name] = float(parts[idx])
                    except ValueError:
                        pass
            if "fps" not in row:
                continue

            # Horodatage : 'elapsed' est en nanosecondes chez MangoHud.
            # Sans cette colonne, on retombe sur le nombre d'échantillons.
            if "elapsed" in row:
                if self._t0 is None:
                    self._t0 = row["elapsed"]
                t = (row["elapsed"] - self._t0) / 1e9
            else:
                t = self._n * (LOG_INTERVAL_MS / 1000.0)
            self._n += 1

            # MangoHud écrit des images à 0 fps au lancement, et le tout
            # début de session est du chargement : on écarte les deux.
            if row["fps"] <= 0 or t < GAME_WARMUP_S:
                continue
            # Jeu suspendu (alt-tab / pause) : ce n'est pas de la performance.
            if row["fps"] < 1000.0 / FREEZE_IGNORE_MS:
                continue

            self._samples.append((t, row["fps"], row.get("frametime")))
            self._last = row

    @staticmethod
    def _percentile(sorted_vals, q):
        """q dans [0,1]. Renvoie la valeur au quantile q (méthode du plus proche rang)."""
        if not sorted_vals:
            return None
        k = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1)))))
        return sorted_vals[k]

    # -- API -------------------------------------------------------------- #
    def sample(self):
        """Renvoie un dict décrivant la session, ou None si aucun jeu actif."""
        if IS_WINDOWS:
            return None
        path, mtime = self._newest_log()
        if not path:
            return None
        if path != self._path:
            self._reset_for(path)
        self._consume(path)

        if not self._samples:
            return None
        live = (time.time() - mtime) <= FPS_STALE_SECONDS

        # Fenêtre glissante : les X dernières secondes de jeu.
        t_end = self._samples[-1][0]
        window = [s for s in self._samples if s[0] >= t_end - GAME_WINDOW_S]
        if not window:
            window = list(self._samples)

        w_fps = [s[1] for s in window]
        vals = sorted(w_fps)
        avg = sum(w_fps) / len(w_fps)
        low1 = self._percentile(vals, 0.01)
        low01 = self._percentile(vals, 0.001)

        all_fps = [s[1] for s in self._samples]
        ft_hist = [s[2] for s in window if s[2] is not None]

        return {
            "live": live,
            "name": self._game_name(path),
            "fps": self._samples[-1][1] if live else None,
            "avg": avg,
            "low1": low1,
            "low01": low01,
            "window_s": min(GAME_WINDOW_S, max(1.0, t_end - window[0][0])),
            "min": min(all_fps),
            "max": max(all_fps),
            "samples": len(self._samples),
            "duration_s": t_end,
            "frametime": ft_hist[-1] if (live and ft_hist) else None,
            "ft_history": ft_hist,
            "cpu_load": self._last.get("cpu_load"),
            "gpu_load": self._last.get("gpu_load"),
            "vram_used": self._last.get("gpu_vram_used"),
        }


def bottleneck(cpu_load, gpu_load):
    """Devine ce qui limite les FPS. Renvoie (texte, couleur)."""
    if cpu_load is None or gpu_load is None:
        return None, None
    if gpu_load >= 95:
        return "GPU à fond — limité par le GPU", C_GPU
    if cpu_load >= 85 and gpu_load < 90:
        return "CPU à fond — limité par le CPU", C_CPU
    if gpu_load < 80 and cpu_load < 80:
        return "Ni CPU ni GPU saturés — limité par le cap FPS / vsync", C_MUTED
    return "Charge équilibrée", C_MUTED


# ----------------------------------------------------------------------------- #
#  Thread d'échantillonnage (évite de bloquer l'UI avec nvidia-smi)
# ----------------------------------------------------------------------------- #

class Sampler(QThread):
    sampled = Signal(dict)

    def __init__(self):
        super().__init__()
        self._running = True
        self.interval_ms = DEFAULT_INTERVAL_MS
        self._cpu = CpuReader()
        self._game = GameReader()

    def run(self):
        while self._running:
            data = {}
            data.update(self._cpu.sample())
            data.update(read_ram())
            data.update(read_gpu())
            data["game"] = self._game.sample()
            self.sampled.emit(data)
            # sommeil découpé pour réagir vite à l'arrêt / changement d'intervalle
            slept = 0
            while self._running and slept < self.interval_ms:
                self.msleep(50)
                slept += 50

    def stop(self):
        self._running = False
        self.wait(2000)


# ----------------------------------------------------------------------------- #
#  Widgets graphiques
# ----------------------------------------------------------------------------- #

class Sparkline(QWidget):
    """Courbe d'historique remplie. max_value=None => échelle auto."""

    def __init__(self, color, max_value=100.0):
        super().__init__()
        self.color = QColor(color)
        self.max_value = max_value
        self.data = deque(maxlen=HISTORY)
        self.setMinimumHeight(54)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def push(self, value):
        self.data.append(value)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if not self.data:
            return
        vals = list(self.data)
        valid = [v for v in vals if v is not None]
        if not valid:
            return

        if self.max_value is not None:
            vmax = self.max_value
        else:
            vmax = max(valid) * 1.15 or 1.0

        n = len(vals)
        step = w / max(1, n - 1)

        def pt(i, v):
            return QPointF(i * step, h - (min(v, vmax) / vmax) * (h - 4) - 2)

        # On découpe en segments contigus (sauts sur les None).
        line = QPen(self.color, 2)
        line.setJoinStyle(Qt.RoundJoin)
        i = 0
        while i < n:
            if vals[i] is None:
                i += 1
                continue
            j = i
            seg = []
            while j < n and vals[j] is not None:
                seg.append((j, vals[j]))
                j += 1
            if len(seg) >= 1:
                path = QPainterPath()
                path.moveTo(pt(seg[0][0], seg[0][1]))
                for k, v in seg[1:]:
                    path.lineTo(pt(k, v))
                # remplissage dégradé sous la courbe
                fill = QPainterPath(path)
                fill.lineTo(QPointF(seg[-1][0] * step, h))
                fill.lineTo(QPointF(seg[0][0] * step, h))
                fill.closeSubpath()
                grad = QLinearGradient(0, 0, 0, h)
                c = QColor(self.color)
                c.setAlpha(90)
                grad.setColorAt(0, c)
                c2 = QColor(self.color)
                c2.setAlpha(0)
                grad.setColorAt(1, c2)
                p.fillPath(fill, QBrush(grad))
                p.strokePath(path, line)
            i = j


class FrametimeGraph(QWidget):
    """Graphe des frametimes (ms). Les pics = micro-saccades ressenties en jeu.

    Une ligne de repère est tracée à la cible (ex. 6,06 ms pour 165 fps) :
    tout ce qui dépasse nettement se voit immédiatement.
    """

    def __init__(self, color=C_FT):
        super().__init__()
        self.color = QColor(color)
        self.data = []
        self.target_ms = 1000.0 / DEFAULT_FPS_TARGET
        self.setMinimumHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, values, target_ms=None):
        # On n'affiche que la fin de la session (le graphe défile).
        self.data = list(values)[-HISTORY:]
        if target_ms:
            self.target_ms = target_ms
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if len(self.data) < 2:
            p.setPen(QColor(C_MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, "en attente de données…")
            return

        # Échelle : au moins 2x la cible, sinon le pic max (avec marge).
        peak = max(self.data)
        top = max(self.target_ms * 2.0, peak * 1.15)

        def y_of(v):
            return h - (min(v, top) / top) * h

        # Ligne de repère (cible)
        ty = y_of(self.target_ms)
        pen = QPen(QColor(C_MUTED), 1, Qt.DashLine)
        p.setPen(pen)
        p.drawLine(0, int(ty), w, int(ty))
        p.setPen(QColor(C_MUTED))
        f = p.font(); f.setPointSize(8); p.setFont(f)
        p.drawText(4, max(10, int(ty) - 3), f"{self.target_ms:.1f} ms")

        # Courbe remplie
        step = w / max(1, len(self.data) - 1)
        path = QPainterPath()
        path.moveTo(0, y_of(self.data[0]))
        for i, v in enumerate(self.data[1:], start=1):
            path.lineTo(i * step, y_of(v))

        fill = QPainterPath(path)
        fill.lineTo(w, h)
        fill.lineTo(0, h)
        fill.closeSubpath()
        grad = QLinearGradient(0, 0, 0, h)
        c = QColor(self.color); c.setAlpha(110)
        grad.setColorAt(0, c)
        c2 = QColor(self.color); c2.setAlpha(10)
        grad.setColorAt(1, c2)
        p.fillPath(fill, QBrush(grad))

        p.setPen(QPen(self.color, 1.6))
        p.drawPath(path)

        # Marqueurs sur les pics importants (> 2x la cible)
        spike = self.target_ms * 2.0
        p.setPen(QPen(QColor(C_BAD), 1))
        p.setBrush(QBrush(QColor(C_BAD)))
        for i, v in enumerate(self.data):
            if v >= spike:
                p.drawEllipse(QPointF(i * step, y_of(v)), 2.2, 2.2)


class CircularGauge(QWidget):
    """Jauge circulaire : anneau de progression + valeur au centre."""

    def __init__(self, color):
        super().__init__()
        self.color = QColor(color)
        self.percent = 0.0
        self.big = "—"
        self.sub = ""
        self.sub_color = QColor(C_MUTED)
        self.setMinimumSize(150, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set(self, percent, big, sub, sub_color=None):
        self.percent = max(0.0, min(100.0, percent))
        self.big = big
        self.sub = sub
        self.sub_color = QColor(sub_color) if sub_color else QColor(C_MUTED)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        side = min(w, h)
        thick = max(8, side * 0.11)
        margin = thick / 2 + 4
        rect = QRectF(
            (w - side) / 2 + margin,
            (h - side) / 2 + margin,
            side - 2 * margin,
            side - 2 * margin,
        )

        # anneau de fond
        bg = QPen(QColor("#272b36"), thick)
        bg.setCapStyle(Qt.RoundCap)
        p.setPen(bg)
        p.drawArc(rect, 0, 360 * 16)

        # arc de progression (départ en haut, sens horaire)
        pen = QPen(self.color, thick)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        span = int(-self.percent / 100.0 * 360 * 16)
        p.drawArc(rect, 90 * 16, span)

        # valeur centrale
        p.setPen(QColor(C_TEXT))
        f = QFont()
        f.setPointSizeF(max(14, side * 0.16))
        f.setBold(True)
        p.setFont(f)
        big_rect = QRectF(rect.x(), rect.y(), rect.width(), rect.height() * 0.70)
        p.drawText(big_rect, Qt.AlignCenter, self.big)

        # sous-texte (peut contenir plusieurs lignes via \n)
        p.setPen(self.sub_color)
        sf = QFont()
        sf.setPointSizeF(max(8, side * 0.058))
        p.setFont(sf)
        sub_rect = QRectF(
            rect.x(), rect.y() + rect.height() * 0.54,
            rect.width(), rect.height() * 0.34,
        )
        p.drawText(sub_rect, Qt.AlignHCenter | Qt.AlignTop, self.sub)


class GaugeCard(QFrame):
    """Carte contenant un titre et une jauge circulaire."""

    def __init__(self, title, color):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(4)

        top = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color}; font-size:12px;")
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        top.addWidget(dot)
        top.addWidget(self.title)
        top.addStretch()
        lay.addLayout(top)

        # Nom du matériel détecté (CPU/GPU/RAM…) sous le titre
        self.hw = QLabel("")
        self.hw.setObjectName("cardHw")
        self.hw.setStyleSheet(f"color:{color};")
        lay.addWidget(self.hw)

        self.gauge = CircularGauge(color)
        lay.addWidget(self.gauge, 1)

        # Courbe de tendance : montre les pics des dernières minutes,
        # que la jauge instantanée ne peut pas révéler.
        self.trend = Sparkline(color, max_value=100.0)
        self.trend.setMinimumHeight(28)
        self.trend.setMaximumHeight(34)
        lay.addWidget(self.trend)

    def update_value(self, percent, big, sub, sub_color=None):
        """Met à jour la jauge ET la courbe de tendance d'un coup."""
        self.gauge.set(percent, big, sub, sub_color)
        self.trend.push(percent)


class MetricCard(QFrame):
    """Carte : titre, grande valeur, sous-texte, sparkline."""

    def __init__(self, title, color, max_value=100.0):
        super().__init__()
        self.color = color
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)

        top = QHBoxLayout()
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{color}; font-size:12px;")
        top.addWidget(dot)
        top.addWidget(self.title)
        top.addStretch()
        self.value = QLabel("—")
        self.value.setObjectName("cardValue")
        top.addWidget(self.value)
        lay.addLayout(top)

        self.sub = QLabel("")
        self.sub.setObjectName("cardSub")
        lay.addWidget(self.sub)

        self.extra = None  # widget optionnel inséré avant la sparkline

        self.spark = Sparkline(color, max_value=max_value)
        lay.addWidget(self.spark, 1)

    def add_extra(self, widget):
        # insère juste avant la sparkline
        self.layout().insertWidget(self.layout().count() - 1, widget)
        self.extra = widget


class StatBox(QVBoxLayout):
    """Petite statistique : grande valeur + libellé dessous."""

    def __init__(self, label, color=C_TEXT, big=False):
        super().__init__()
        self.setSpacing(0)
        self.value = QLabel("—")
        self.value.setStyleSheet(
            f"color:{color}; font-size:{'34' if big else '20'}px; font-weight:700;"
        )
        self.value.setAlignment(Qt.AlignCenter)
        cap = QLabel(label)
        cap.setObjectName("cardSub")
        cap.setAlignment(Qt.AlignCenter)
        self.addWidget(self.value)
        self.addWidget(cap)

    def set(self, text, color=None):
        self.value.setText(text)
        if color:
            self.value.setStyleSheet(
                self.value.styleSheet().split("color:")[0] + f"color:{color};" +
                ";".join(self.value.styleSheet().split(";")[1:])
            )


class GamePanel(QFrame):
    """Panneau gaming : FPS, 1% low, 0.1% low, frametime et goulot d'étranglement.

    Le 1% low est ce qui se ressent vraiment en jeu : une moyenne de 120 fps
    avec un 1% low à 40 donne une expérience saccadée.
    """

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        # En-tête : titre + nom du jeu détecté
        top = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{C_FPS}; font-size:12px;")
        t = QLabel("EN JEU")
        t.setObjectName("cardTitle")
        top.addWidget(dot)
        top.addWidget(t)
        top.addStretch()
        self.game = QLabel("")
        self.game.setObjectName("cardHw")
        self.game.setStyleSheet(f"color:{C_FPS};")
        top.addWidget(self.game)
        lay.addLayout(top)

        # Ligne de statistiques
        stats = QHBoxLayout()
        stats.setSpacing(6)
        self.s_fps = StatBox("FPS", C_FPS, big=True)
        self.s_low1 = StatBox("1% LOW (60 s)", C_TEXT)
        self.s_low01 = StatBox("0.1% LOW (60 s)", C_TEXT)
        self.s_avg = StatBox("MOYENNE (60 s)", C_MUTED)
        self.s_ft = StatBox("FRAMETIME", C_FT)
        for s in (self.s_fps, self.s_low1, self.s_low01, self.s_avg, self.s_ft):
            stats.addLayout(s)
        lay.addLayout(stats)

        # Goulot d'étranglement
        self.bottle = QLabel("")
        self.bottle.setObjectName("cardSub")
        self.bottle.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.bottle)

        # Graphe de frametime
        self.ft_graph = FrametimeGraph()
        lay.addWidget(self.ft_graph, 1)

        self.status = QLabel("Aucun jeu détecté — lance un jeu avec MangoHud")
        self.status.setObjectName("cardSub")
        self.status.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.status)

    def _fps_color(self, v, target):
        if v is None:
            return C_MUTED
        if v >= target * 0.85:
            return C_OK
        if v >= target * 0.5:
            return C_WARN
        return C_BAD

    def clear(self):
        for s in (self.s_fps, self.s_low1, self.s_low01, self.s_avg, self.s_ft):
            s.value.setText("—")
        self.game.setText("")
        self.bottle.setText("")
        self.ft_graph.set_data([])
        self.status.setText("Aucun jeu détecté — lance un jeu avec MangoHud")

    def update_game(self, g, target):
        self.game.setText(g["name"])

        if g["live"] and g["fps"] is not None:
            self.s_fps.set(f"{g['fps']:.0f}", self._fps_color(g["fps"], target))
        else:
            self.s_fps.set("—", C_MUTED)

        self.s_low1.set(f"{g['low1']:.0f}", self._fps_color(g["low1"], target))
        self.s_low01.set(f"{g['low01']:.0f}", self._fps_color(g["low01"], target))
        self.s_avg.set(f"{g['avg']:.0f}")

        ft = g["frametime"]
        self.s_ft.set(f"{ft:.1f} ms" if ft else "—")

        txt, col = bottleneck(g["cpu_load"], g["gpu_load"])
        if txt:
            self.bottle.setText(txt)
            self.bottle.setStyleSheet(f"color:{col}; font-size:12px; font-weight:600;")
        else:
            self.bottle.setText("")

        self.ft_graph.set_data(g["ft_history"], target_ms=1000.0 / target)

        etat = "Session en cours" if g["live"] else "Dernière session (terminée)"
        self.status.setText(
            f"{etat} · {g['duration_s']/60:.1f} min de jeu · "
            f"lows sur les {g['window_s']:.0f} dernières s · "
            f"extrêmes session {g['min']:.0f}–{g['max']:.0f} fps"
        )


# ----------------------------------------------------------------------------- #
#  Fenêtre principale
# ----------------------------------------------------------------------------- #

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CachyMonitor")
        self.resize(560, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        # En-tête
        header = QHBoxLayout()
        title = QLabel("CachyMonitor")
        title.setObjectName("appTitle")
        header.addWidget(title)
        header.addStretch()

        header.addWidget(QLabel("Intervalle"))
        self.interval = QSpinBox()
        self.interval.setRange(200, 5000)
        self.interval.setSingleStep(100)
        self.interval.setValue(DEFAULT_INTERVAL_MS)
        self.interval.setSuffix(" ms")
        self.interval.valueChanged.connect(self._set_interval)
        header.addWidget(self.interval)

        header.addWidget(QLabel("Cible FPS"))
        self.fps_target = QSpinBox()
        self.fps_target.setRange(30, 500)
        self.fps_target.setSingleStep(5)
        self.fps_target.setValue(DEFAULT_FPS_TARGET)
        self.fps_target.setToolTip(
            "Sert d'échelle aux couleurs FPS et de repère sur le graphe de frametime"
        )
        header.addWidget(self.fps_target)

        self.ontop = QCheckBox("Au-dessus")
        self.ontop.toggled.connect(self._toggle_ontop)
        header.addWidget(self.ontop)
        root.addLayout(header)

        # Cartes
        grid = QGridLayout()
        grid.setSpacing(14)

        self.cpu = GaugeCard("CPU", C_CPU)
        self.gpu = GaugeCard("GPU", C_GPU)
        self.ram = GaugeCard("RAM", C_RAM)
        self.vram = GaugeCard("VRAM", C_VRAM)
        self.game = GamePanel()

        grid.addWidget(self.cpu, 0, 0)
        grid.addWidget(self.gpu, 0, 1)
        grid.addWidget(self.ram, 1, 0)
        grid.addWidget(self.vram, 1, 1)
        grid.addWidget(self.game, 2, 0, 1, 2)
        grid.setRowStretch(2, 1)
        root.addLayout(grid, 1)

        # Noms matériel statiques (lus une seule fois)
        self.cpu.hw.setText(read_cpu_name())
        self.ram.hw.setText(read_ram_name())

        self.status = QLabel("Démarrage…")
        self.status.setObjectName("status")
        root.addWidget(self.status)

        # Réglages mémorisés (intervalle, cible FPS, "au-dessus", géométrie)
        self._load_settings()

        # Sampler
        self.sampler = Sampler()
        self.sampler.interval_ms = self.interval.value()
        self.sampler.sampled.connect(self.on_sample)
        self.sampler.start()

    # -- handlers ----------------------------------------------------------- #
    def _set_interval(self, v):
        self.sampler.interval_ms = v

    def _toggle_ontop(self, on):
        flag = Qt.WindowStaysOnTopHint
        self.setWindowFlag(flag, on)
        self.show()

    def on_sample(self, d):
        # CPU
        t = d["cpu_temp"]
        freq = f"{d['cpu_freq']/1000:.2f} GHz" if d["cpu_freq"] else "—"
        ttxt = f"{t:.0f}°C" if t is not None else "—"
        self.cpu.update_value(d["cpu_pct"], f"{d['cpu_pct']:.0f}%",
                              f"{freq}\n{ttxt}", temp_color(t))

        # GPU
        gpu_name = d["gpu_name"].replace("NVIDIA ", "")
        if self.gpu.hw.text() != gpu_name:
            self.gpu.hw.setText(gpu_name)
            self.vram.hw.setText(gpu_name)
        gt = d["gpu_temp"]
        gttxt = f"{gt:.0f}°C" if gt is not None else "—"
        pw = f"{d['gpu_power']:.0f} W" if d["gpu_power"] else "—"
        self.gpu.update_value(d["gpu_pct"], f"{d['gpu_pct']:.0f}%",
                              f"{pw}\n{gttxt}", temp_color(gt))

        # RAM
        self.ram.update_value(d["ram_pct"], f"{d['ram_pct']:.0f}%",
                              f"{d['ram_used']:.1f} / {d['ram_total']:.1f} Gio")

        # VRAM
        vt, vu = d["vram_total"], d["vram_used"]
        vpct = (vu / vt * 100) if vt else 0
        self.vram.update_value(vpct, f"{vpct:.0f}%",
                               f"{vu/1024:.1f} / {vt/1024:.1f} Gio")

        # Session de jeu (MangoHud)
        g = d.get("game")
        if g is None:
            self.game.clear()
        else:
            self.game.update_game(g, self.fps_target.value())

        self.status.setText(
            f"Mise à jour toutes les {self.sampler.interval_ms} ms · "
            f"{time.strftime('%H:%M:%S')}"
        )

    # -- persistance des réglages ------------------------------------------- #
    def _load_settings(self):
        """Restaure les réglages. Appelé AVANT la création du sampler : on coupe
        les signaux pendant la restauration, sinon _set_interval s'exécuterait
        alors que self.sampler n'existe pas encore."""
        s = QSettings("CachyMonitor", "CachyMonitor")

        for widget, key, default in (
            (self.interval, "interval_ms", DEFAULT_INTERVAL_MS),
            (self.fps_target, "fps_target", DEFAULT_FPS_TARGET),
        ):
            try:
                value = int(s.value(key, default))
            except (TypeError, ValueError):
                value = default
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)

        # QSettings renvoie les booléens en texte selon le backend.
        ontop = s.value("ontop", False)
        if isinstance(ontop, str):
            ontop = ontop.lower() in ("true", "1", "yes")
        if ontop:
            self.ontop.blockSignals(True)
            self.ontop.setChecked(True)
            self.ontop.blockSignals(False)
            # On applique le drapeau sans appeler show() (la fenêtre n'est pas
            # encore affichée à ce stade).
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        geo = s.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)

    def _save_settings(self):
        s = QSettings("CachyMonitor", "CachyMonitor")
        s.setValue("interval_ms", self.interval.value())
        s.setValue("fps_target", self.fps_target.value())
        s.setValue("ontop", self.ontop.isChecked())
        s.setValue("geometry", self.saveGeometry())

    def closeEvent(self, e):
        self._save_settings()
        self.sampler.stop()
        super().closeEvent(e)


STYLE = f"""
QWidget {{ background: {C_BG}; color: {C_TEXT}; font-family: 'Inter','Noto Sans',sans-serif; font-size: 13px; }}
#appTitle {{ font-size: 20px; font-weight: 700; }}
#card {{ background: {C_CARD}; border-radius: 14px; }}
#cardTitle {{ color: {C_MUTED}; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }}
#cardHw {{ font-size: 11px; font-weight: 600; }}
#cardValue {{ font-size: 26px; font-weight: 700; }}
#cardSub {{ color: {C_MUTED}; font-size: 12px; }}
#status {{ color: {C_MUTED}; font-size: 11px; }}
QSpinBox {{ background: {C_CARD}; border: 1px solid #2a2e3a; border-radius: 6px; padding: 2px 6px; }}
QCheckBox {{ color: {C_MUTED}; }}
"""


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("CachyMonitor")
    icon_path = os.path.join(os.path.dirname(__file__), "cachymonitor.svg")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    else:
        app.setWindowIcon(QIcon.fromTheme("utilities-system-monitor"))
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
