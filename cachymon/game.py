"""CachyMonitor : module game (voir cachymonitor.py)."""

import os
import re
import glob
import time
from collections import deque

from .config import FPS_LOG_DIRS, FPS_STALE_SECONDS, FREEZE_IGNORE_MS, GAME_HISTORY, GAME_WARMUP_S, GAME_WINDOW_S, LOG_INTERVAL_MS
from .i18n import tr



def _percentile(sorted_vals, q):
    """q dans [0,1]. Renvoie la valeur au quantile q (méthode du plus proche rang)."""
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def game_stats(samples, live, name, extra=None):
    """Statistiques d'une session à partir d'échantillons (t_s, fps, frametime_ms).

    Commun aux deux plateformes : MangoHud et RTSS ne diffèrent que par la façon
    de collecter les échantillons, pas par le sens des chiffres qu'on en tire.
    Les « lows » portent sur une fenêtre glissante des GAME_WINDOW_S dernières
    secondes — sur une session entière, un écran de chargement en milieu de
    partie plomberait définitivement le 0.1% low alors qu'il ne dit rien de la
    fluidité actuelle.
    """
    if not samples:
        return None

    t_end = samples[-1][0]
    window = [s for s in samples if s[0] >= t_end - GAME_WINDOW_S] or list(samples)

    w_fps = [s[1] for s in window]
    vals = sorted(w_fps)
    all_fps = [s[1] for s in samples]
    ft_hist = [s[2] for s in window if s[2] is not None]

    stats = {
        "live": live,
        "name": name,
        "fps": samples[-1][1] if live else None,
        "avg": sum(w_fps) / len(w_fps),
        "low1": _percentile(vals, 0.01),
        "low01": _percentile(vals, 0.001),
        "window_s": min(GAME_WINDOW_S, max(1.0, t_end - window[0][0])),
        "min": min(all_fps),
        "max": max(all_fps),
        "samples": len(samples),
        "duration_s": t_end,
        "frametime": ft_hist[-1] if (live and ft_hist) else None,
        "ft_history": ft_hist,
        "cpu_load": None,
        "gpu_load": None,
        "vram_used": None,
    }
    if extra:
        stats.update(extra)
    return stats


class MangoHudGameReader:
    """Lit une session de jeu depuis le log CSV MangoHud le plus récent (Linux).

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
    WANTED = ("fps", "frametime", "cpu_load", "gpu_load", "gpu_vram_used", "elapsed")

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
        return base.replace("_", " ").strip().title() or tr("Game")

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

    # -- API -------------------------------------------------------------- #
    def sample(self):
        """Renvoie un dict décrivant la session, ou None si aucun jeu actif."""
        path, mtime = self._newest_log()
        if not path:
            return None
        if path != self._path:
            self._reset_for(path)
        self._consume(path)

        live = (time.time() - mtime) <= FPS_STALE_SECONDS
        return game_stats(
            list(self._samples), live, self._game_name(path),
            extra={
                "cpu_load": self._last.get("cpu_load"),
                "gpu_load": self._last.get("gpu_load"),
                "vram_used": self._last.get("gpu_vram_used"),
            },
        )

    def start(self):
        """Rien à démarrer : la lecture se fait dans le thread d'échantillonnage."""

    def stop(self):
        """Rien à arrêter : la lecture se fait dans le thread d'échantillonnage."""


def bottleneck(cpu_load, gpu_load):
    """Devine ce qui limite les FPS. Renvoie (texte, rôle de couleur)."""
    if cpu_load is None or gpu_load is None:
        return None, None
    if gpu_load >= 95:
        return tr("GPU maxed out — GPU-bound"), "gpu"
    if cpu_load >= 85 and gpu_load < 90:
        return tr("CPU maxed out — CPU-bound"), "cpu"
    if gpu_load < 80 and cpu_load < 80:
        return tr("Neither CPU nor GPU saturated — limited by FPS cap / vsync"), "muted"
    return tr("Balanced load"), "muted"
