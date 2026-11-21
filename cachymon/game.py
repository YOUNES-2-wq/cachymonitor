"""CachyMonitor : module game (voir cachymonitor.py)."""

from .config import GAME_WINDOW_S
from .i18n import tr



def _percentile(sorted_vals, q):
    """q dans [0,1]. Renvoie la valeur au quantile q (méthode du plus proche rang)."""
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def game_stats(samples, live, name, extra=None):
    """Statistiques d'une session à partir d'échantillons (t_s, fps, frametime_ms).

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
