"""CachyMonitor : module game_windows (voir cachymonitor.py)."""

import os
import re
import sys
import time
import subprocess
import threading
from collections import deque
from PySide6.QtCore import QThread
from .config import APP_ROOT, FPS_STALE_SECONDS, FREEZE_IGNORE_MS, GAME_HISTORY, GAME_WARMUP_S, IS_WINDOWS, MAX_PATH, RTSS_SHARED_MEMORY, SHM_MAX_SIZE, WIN_POLL_MS, _NO_WINDOW, asset_dir, plausible_fps
from .debug import debug_exc
from .game import MangoHudGameReader, game_stats
from .i18n import tr
from .winshm import AB, _read_shared_memory



class RtssGameReader:
    """Session de jeu sous Windows, mesurée sur la mémoire partagée de RivaTuner.

    RTSS tient, pour chaque application accrochée, un compteur d'images qui
    n'avance que quand elle dessine. On l'échantillonne toutes les WIN_POLL_MS
    dans un thread dédié — le thread principal, lui, ne tique qu'une fois par
    seconde, ce qui donnerait 60 points par minute et rendrait le 0.1% low
    dénué de sens.

    Choisir la bonne application est le point délicat : RTSS accroche aussi
    l'explorateur, les navigateurs et les launchers, qui affichent volontiers
    120 fps sur le bureau. Deux garde-fous :
      * Afterburner sert d'arbitre — son capteur « Framerate » n'est actif que
        lorsqu'un jeu tourne réellement ;
      * à défaut, on suit la fenêtre au premier plan.
    """

    SIGNATURES = (0x53535452, 0x52545353)   # RTSS < 7, puis RTSS 7.x

    @staticmethod
    def _afterburner_fps():
        """FPS publié par Afterburner, ou None si aucun jeu ne tourne.

        Hors jeu, le capteur ne vaut pas toujours FLT_MAX : Afterburner le
        remet aussi à 0 selon le moment. Les deux cas signifient « pas de jeu ».
        """
        return plausible_fps(AB.get("Framerate"))

    def __init__(self):
        self._samples = deque(maxlen=GAME_HISTORY)
        self._pid = None          # application suivie
        self._name = None
        self._t0 = None           # instant de départ de la session
        self._prev = None         # (compteur d'images, instant) du tour précédent
        self._last_seen = 0.0     # dernière image effectivement comptée
        self._poller = None

    # -- collecte (thread dédié) ------------------------------------------ #
    def start(self):
        if self._poller is None:
            self._poller = _GamePoller(self)
            self._poller.start()

    def stop(self):
        if self._poller is not None:
            self._poller.stop()
            self._poller = None

    def _entries(self, data):
        """Itère les applications accrochées : (pid, chemin_exe_brut, compteur_images).

        Le chemin reste en octets : RTSS accroche aussi le bureau, les navigateurs
        et les launchers, et seule l'entrée finalement retenue mérite d'être
        décodée — ici on passerait dix fois par seconde sur toutes les autres.
        """
        import struct
        sig, _ver, entry_sz, arr_off, arr_cnt = struct.unpack_from("<IIIII", data, 0)

        # RTSS 7.x a déplacé les champs de l'entrée (structure confirmée par
        # analyse différentielle de la mémoire pendant une partie).
        if sig == 0x52545353:
            pid_off, name_off, fc_off, min_size = 0, 4, 296, 300
        else:
            pid_off, name_off, fc_off, min_size = 4, 12, 272, 280

        for i in range(arr_cnt):
            base = arr_off + i * entry_sz
            if base + min_size > len(data):
                return
            pid = struct.unpack_from("<I", data, base + pid_off)[0]
            if pid == 0:
                continue
            path = data[base + name_off:base + name_off + MAX_PATH].split(b"\0")[0]
            frames = struct.unpack_from("<I", data, base + fc_off)[0]
            yield pid, path, frames

    def _read_entries(self):
        import struct

        def total_size(header):
            sig, _ver, entry_sz, arr_off, arr_cnt = struct.unpack_from("<IIIII", header, 0)
            if sig not in self.SIGNATURES or entry_sz == 0 or arr_cnt == 0:
                return None
            # Garde-fous contre un en-tête corrompu (RTSS 7.x occupe ~5,3 Mo).
            if entry_sz > 131072 or arr_cnt > 1024 or arr_off > SHM_MAX_SIZE:
                return None
            total = arr_off + arr_cnt * entry_sz
            return total if total <= SHM_MAX_SIZE else None

        data = _read_shared_memory(RTSS_SHARED_MEMORY, total_size)
        if not data:
            return []
        try:
            return list(self._entries(data))
        except Exception:
            return []

    @staticmethod
    def _foreground_pid():
        """PID de la fenêtre active (0 si indéterminé)."""
        try:
            import ctypes
            u32 = ctypes.windll.user32
            u32.GetForegroundWindow.restype = ctypes.c_void_p
            hwnd = u32.GetForegroundWindow()
            if not hwnd:
                return 0
            pid = ctypes.c_uint32(0)
            u32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
            return pid.value
        except Exception:
            return 0

    @staticmethod
    def _game_name(path):
        """b'D:\\...\\RDR2.exe' -> 'Rdr2'"""
        base = os.path.basename(path.decode("latin-1", "ignore").replace("\\", "/"))
        base = re.sub(r"\.exe$", "", base, flags=re.I)
        return base.replace("_", " ").strip().title() or tr("Game")

    def _pick(self, entries):
        """Entrée correspondant au jeu, ou None."""
        if not entries:
            return None
        # Afterburner ne publie un « Framerate » exploitable que lorsqu'un jeu
        # tourne : sans ce signal, tout ce que RTSS accroche n'est que du bureau
        # (le dock, le navigateur… qui tournent volontiers à 120 fps).
        if AB.available() and self._afterburner_fps() is None:
            return None

        by_pid = {pid: (pid, path, frames) for pid, path, frames in entries}

        if self._pid in by_pid:          # on reste sur le jeu déjà suivi
            return by_pid[self._pid]
        foreground = self._foreground_pid()
        if foreground in by_pid:
            return by_pid[foreground]
        return None

    def poll(self):
        """Un relevé. Appelé toutes les WIN_POLL_MS par le thread dédié."""
        entry = self._pick(self._read_entries())
        now = time.monotonic()
        if entry is None:
            self._prev = None       # le delta d'après serait faussé par la coupure
            return

        pid, path, frames = entry
        if pid != self._pid:        # nouveau jeu : on repart de zéro
            self._samples.clear()
            self._pid = pid
            self._name = self._game_name(path)
            self._t0 = now
            self._prev = None

        prev = self._prev
        self._prev = (frames, now)
        if prev is None:
            return
        prev_frames, prev_t = prev
        dt = now - prev_t
        df = frames - prev_frames
        if not (0.02 < dt < 5.0) or df <= 0:
            return

        fps = plausible_fps(df / dt)
        if fps is None:
            return
        t = now - self._t0
        # Mêmes exclusions que sous Linux : le tout début de session est du
        # chargement, et une image de plus d'une seconde est un jeu suspendu.
        if t < GAME_WARMUP_S or fps < 1000.0 / FREEZE_IGNORE_MS:
            return
        # Le frametime est déduit du débit d'images sur la fenêtre de 100 ms :
        # RTSS ne publie pas la durée image par image, donc les pics les plus
        # brefs sont lissés — c'est la limite de cette source face à MangoHud.
        self._samples.append((t, fps, 1000.0 / fps))
        self._last_seen = now

    # -- API -------------------------------------------------------------- #
    def sample(self):
        if not self._samples:
            return None
        live = (time.monotonic() - self._last_seen) <= FPS_STALE_SECONDS
        # Le FPS montré est celui d'Afterburner quand il est disponible : c'est
        # le chiffre que RivaTuner affiche en jeu, à l'identique.
        extra = {}
        shown = self._afterburner_fps()
        if live and shown is not None:
            extra["fps"] = shown
        return game_stats(list(self._samples), live, self._name, extra=extra)


class _GamePoller(QThread):
    """Thread de relevé haute fréquence du lecteur de jeu Windows."""

    def __init__(self, reader):
        super().__init__()
        self._reader = reader
        self._running = True

    def run(self):
        while self._running:
            try:
                self._reader.poll()
            except Exception:
                debug_exc("releve du jeu")      # un relevé raté ne doit pas tuer le thread
            self.msleep(WIN_POLL_MS)

    def stop(self):
        self._running = False
        self.wait(2000)


# ----------------------------------------------------------------------------- #
#  PresentMon (Windows) : FPS sans Afterburner ni RivaTuner
# ----------------------------------------------------------------------------- #
#
# PresentMon est l'outil d'Intel (licence MIT) qui lit, par les traces ETW de
# Windows, chaque image présentée par chaque application. Il ne s'injecte pas
# dans le jeu, contrairement à RivaTuner : les anti-triches le tolèrent (vérifié
# sur eFootball le 08/11/2026). Sans élévation, Windows exige que le compte soit
# dans le groupe « Utilisateurs du journal de performances » (S-1-5-32-559),
# ce que propose l'installateur.
#
# En 1.5.x, c'était une source de secours. Depuis 1.6.0, c'est la source
# PRINCIPALE : PresentMon suit le jeu par son process, même quand il n'est plus
# au premier plan (Afterburner ne publie le FPS que de la fenêtre active).
# RivaTuner prend le relais quand PresentMon ne mesure rien : PresentMon
# absent ou refusé (compte hors du groupe), ou jeu en fenêtre classique.

PRESENTMON_EXE = "PresentMon.exe"
PRESENTMON_SESSION = "CachyMonitor"
PRESENTMON_RETRY_S = 30.0      # attente avant de relancer PresentMon après un échec
PRESENTMON_SEEN_S = 1.0        # une appli sans image depuis 1 s ne « dessine » plus

# Programmes qui présentent des images sans être des jeux : le bureau, les docks,
# les navigateurs, les overlays. Bug n°10 : le dock MyDockFinder tournait à
# 120 fps sur le bureau et passait pour un jeu. Les noms sont en minuscules.
PRESENTMON_IGNORE = frozenset({
    "dwm.exe", "explorer.exe", "cachymonitor.exe", "python.exe", "pythonw.exe",
    "mydockfinder.exe", "wallpaper32.exe", "wallpaper64.exe", "lively.exe",
    "windowsterminal.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "textinputhost.exe", "applicationframehost.exe",
    "tabtip.exe", "widgets.exe", "msedge.exe", "msedgewebview2.exe", "chrome.exe",
    "firefox.exe", "opera.exe", "brave.exe", "vivaldi.exe", "zen.exe",
    "librewolf.exe", "waterfox.exe", "floorp.exe", "arc.exe", "discord.exe",
    "spotify.exe", "vlc.exe", "mpc-hc64.exe", "mpv.exe",
    "steam.exe", "steamwebhelper.exe", "gameoverlayui.exe", "gameoverlayui64.exe",
    "epicgameslauncher.exe", "eadesktop.exe", "upc.exe", "battle.net.exe",
    "msiafterburner.exe", "rtss.exe", "nvidia overlay.exe", "nvcontainer.exe",
    "radeonsoftware.exe", "razercortex.exe", "razer central.exe",
    "razerappengine.exe", "windhawk.exe", "code.exe", "obs64.exe",
})

# État du lecteur PresentMon, lu par no_game_text() pour guider l'utilisateur :
# "absent" (exécutable introuvable), "starting", "running", "denied" (compte
# hors du groupe), "error".
PRESENTMON_STATE = "absent"


def presentmon_state():
    """Etat courant de PresentMon. A appeler a chaque lecture : la valeur change en
    cours de route, un `from ... import PRESENTMON_STATE` la figerait."""
    return PRESENTMON_STATE


def find_presentmon():
    """Chemin de PresentMon.exe, ou None.

    L'installateur le pose à côté de CachyMonitor.exe. La variable
    CACHYMONITOR_PRESENTMON permet de tester une autre copie sans réinstaller.
    """
    env = os.environ.get("CACHYMONITOR_PRESENTMON")
    candidates = [env] if env else []
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(os.path.dirname(sys.executable), PRESENTMON_EXE))
    candidates.append(os.path.join(asset_dir(), PRESENTMON_EXE))
    candidates.append(os.path.join(APP_ROOT,
                                   PRESENTMON_EXE))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _kill_with_parent_job(proc):
    """Lie le sous-processus à un « job » Windows fermé avec CachyMonitor.

    Si CachyMonitor plante ou est tué, Windows ferme le job et tue PresentMon
    avec lui : jamais de PresentMon orphelin qui tournerait en tâche de fond.
    Renvoie le handle du job (à garder vivant), ou None.
    """
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC_LIMIT),
                        ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        k32.CreateJobObjectW.restype = ctypes.c_void_p
        k32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                           ctypes.byref(info), ctypes.sizeof(info)):
            k32.CloseHandle(ctypes.c_void_p(job))
            return None
        # Popen._handle est le handle Windows du processus : l'API publique de
        # subprocess n'en donne pas d'autre.
        if not k32.AssignProcessToJobObject(job, ctypes.c_void_p(int(proc._handle))):
            k32.CloseHandle(ctypes.c_void_p(job))
            return None
        return job
    except Exception:
        return None


def _close_handle(handle):
    """Ferme un handle Windows (job de _kill_with_parent_job) ; None accepté."""
    if handle:
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        except Exception:
            pass


class PresentMonGameReader:
    """Session de jeu mesurée par PresentMon, lancé en sous-processus.

    PresentMon écrit une ligne CSV par image présentée, toutes applications
    confondues. Un thread lit ce flux et empile les images ; le relevé de
    WIN_POLL_MS (le même _GamePoller que RivaTuner) les regroupe ensuite par
    tranches de 100 ms. Les chiffres ont ainsi le même sens qu'avec RivaTuner et
    MangoHud : un échantillon = un débit moyen sur 100 ms.

    Choix de l'application, garde-fou du bug n°10 compris :
      * on reste sur le jeu déjà suivi tant qu'il dessine, même s'il n'est plus
        au premier plan (c'est tout l'intérêt face à Afterburner) ;
      * sinon on adopte la fenêtre au premier plan, à trois conditions : elle
        dessine, elle couvre TOUT son écran (plein écran ou fenêtre sans bord,
        comme un jeu), et ce n'est pas un programme du bureau
        (PRESENTMON_IGNORE).
    Rien n'est jamais choisi à l'aveugle : le 08/11/2026, un navigateur au
    premier plan (Zen, 30-40 fps) passait pour un jeu, et le mode de
    présentation « Hardware » ne suffisait pas à l'écarter. Limite assumée : un
    jeu en fenêtre classique n'est pas détecté par PresentMon (RivaTuner, lui,
    le voit).

    Deux threads, deux rôles :
      * le thread « presentmon » possède le sous-processus : il le lance, lit
        son flux, le nettoie et le relance après un échec. Lui seul y touche ;
      * le _GamePoller appelle poll() toutes les WIN_POLL_MS.
    Seule la liste _pending est partagée entre eux, sous verrou.
    """

    SOURCE = "PresentMon"

    def __init__(self, exe):
        self._exe = exe
        self._lock = threading.Lock()
        self._pending = []        # (pid, exe, ms) reçus depuis le dernier relevé
        self._seen = {}           # pid -> (exe, dernier instant où il a dessiné)
        self._samples = deque(maxlen=GAME_HISTORY)
        self._pid = None          # application suivie
        self._name = None
        self._t0 = None           # instant de départ de la session
        self._last_seen = 0.0     # dernière image effectivement comptée
        self._proc = None
        self._running = False
        self._thread = None
        self._poller = None

    # -- cycle de vie ------------------------------------------------------ #
    def start(self):
        global PRESENTMON_STATE
        if self._running:
            return
        self._running = True
        PRESENTMON_STATE = "starting"
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="presentmon")
        self._thread.start()
        self._poller = _GamePoller(self)
        self._poller.start()

    def stop(self):
        """Arrêt propre : on clôt la session ETW de PresentMon.

        PresentMon s'arrête alors de lui-même, son flux se ferme, et le thread
        « presentmon » fait le ménage. Tuer PresentMon d'emblée laisserait sa
        session ETW ouverte jusqu'au prochain lancement.
        """
        self._running = False
        if self._poller is not None:
            self._poller.stop()
            self._poller = None
        try:
            subprocess.run(self._command("--terminate_existing_session"),
                           timeout=5, capture_output=True, **_NO_WINDOW)
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(5)
            self._thread = None
        proc = self._proc
        if proc is not None:        # PresentMon sourd à la demande : en dernier recours
            try:
                proc.kill()
            except Exception:
                pass

    def _command(self, *extra):
        return [self._exe, "--session_name", PRESENTMON_SESSION, *extra]

    # -- thread « presentmon » -------------------------------------------- #
    def _run(self):
        """Lance PresentMon, lit son flux, le relance s'il s'arrête."""
        global PRESENTMON_STATE
        excludes = [arg for name in sorted(PRESENTMON_IGNORE)
                    for arg in ("--exclude", name)]
        while self._running:
            denied = False
            job = None
            try:
                # Les messages d'erreur (stderr) arrivent dans le même flux que
                # le CSV : un seul tuyau à lire, donc aucun risque de blocage
                # si PresentMon remplit l'autre pendant qu'on lit le premier.
                self._proc = subprocess.Popen(
                    self._command("--output_stdout", "--no_console_stats",
                                  "--stop_existing_session", "--no_track_input",
                                  "--no_track_gpu", *excludes),
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                    errors="replace", bufsize=1, **_NO_WINDOW)
                job = _kill_with_parent_job(self._proc)
                denied = self._read_stream(self._proc.stdout)
                self._proc.wait(5)
            except subprocess.TimeoutExpired:
                pass        # PresentMon met du temps a quitter : arret force plus bas
            except Exception:
                debug_exc("PresentMon")
            finally:
                if self._proc is not None and self._proc.poll() is None:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                self._proc = None
                _close_handle(job)
            if not self._running:
                break
            PRESENTMON_STATE = "denied" if denied else "error"
            # Pas de relance en boucle serrée : un PresentMon qui échoue à
            # chaque fois ne doit pas occuper le processeur.
            deadline = time.monotonic() + PRESENTMON_RETRY_S
            while self._running and time.monotonic() < deadline:
                time.sleep(0.25)

    def _read_stream(self, stream):
        """Lit le flux jusqu'à sa fin. Renvoie True si l'accès a été refusé.

        On lit jusqu'au bout même pendant l'arrêt : un tuyau qu'on cesse de vider
        bloque PresentMon sur sa dernière écriture, et il ne peut plus quitter
        (constaté le 08/11/2026 : 5 s d'attente, puis arrêt forcé).
        """
        global PRESENTMON_STATE
        cols = None
        for line in stream:
            if cols is None:
                # Avant l'en-tête CSV, PresentMon n'écrit que des messages.
                if "access denied" in line.lower():
                    return True
                if line.startswith("Application,"):
                    cols = line.strip().split(",")
                    try:
                        i_app = cols.index("Application")
                        i_pid = cols.index("ProcessID")
                        i_ms = cols.index("MsBetweenPresents")
                    except ValueError:
                        return False    # format inattendu : on ne devine pas
                    need = max(i_app, i_pid, i_ms) + 1
                    PRESENTMON_STATE = "running"
                continue
            parts = line.rstrip("\r\n").split(",")
            if len(parts) < need:
                continue                # message isolé au milieu du CSV
            try:
                ms = float(parts[i_ms])
                pid = int(parts[i_pid])
            except ValueError:
                continue                # « NA » sur la première image d'une appli
            if ms <= 0:
                continue
            with self._lock:
                self._pending.append((pid, parts[i_app], ms))
        return False

    # -- relevé (thread _GamePoller) -------------------------------------- #
    def _pick(self, now):
        """PID du jeu, ou None."""
        alive = {pid: exe for pid, (exe, last) in self._seen.items()
                 if now - last <= PRESENTMON_SEEN_S}
        if self._pid in alive:
            return self._pid
        foreground, fullscreen = _foreground_fullscreen()
        if foreground not in alive or not fullscreen:
            return None
        exe = alive[foreground].lower()
        if exe in PRESENTMON_IGNORE or exe == "<unknown>":
            return None
        return foreground

    def poll(self):
        """Un relevé. Appelé toutes les WIN_POLL_MS par le _GamePoller."""
        with self._lock:
            frames, self._pending = self._pending, []
        now = time.monotonic()

        # Par application : nombre d'images et durée cumulée sur la tranche.
        # Une image de plus de FREEZE_IGNORE_MS est un jeu suspendu (alt-tab,
        # pause) : comptée, elle ferait plonger le débit de la tranche où le jeu
        # reprend, et donnerait une fausse saccade.
        per_pid = {}
        for pid, exe, ms in frames:
            self._seen[pid] = (exe, now)
            if ms > FREEZE_IGNORE_MS:
                continue
            count, total = per_pid.get(pid, (0, 0.0))
            per_pid[pid] = (count + 1, total + ms)
        # On oublie les applis qui ne dessinent plus depuis longtemps.
        self._seen = {pid: s for pid, s in self._seen.items() if now - s[1] < 30}

        pid = self._pick(now)
        if pid is None:
            return
        if pid != self._pid:            # nouveau jeu : on repart de zéro
            self._samples.clear()
            self._pid = pid
            self._name = _exe_to_game_name(self._seen[pid][0])
            self._t0 = now
        count, total = per_pid.get(pid, (0, 0.0))
        if count == 0 or total <= 0:
            return
        fps = plausible_fps(count * 1000.0 / total)
        if fps is None:
            return
        t = now - self._t0
        # Même exclusion que RivaTuner et MangoHud : le début de session est
        # du chargement.
        if t < GAME_WARMUP_S:
            return
        self._samples.append((t, fps, 1000.0 / fps))
        self._last_seen = now

    # -- API -------------------------------------------------------------- #
    def sample(self):
        if not self._samples:
            return None
        live = (time.monotonic() - self._last_seen) <= FPS_STALE_SECONDS
        return game_stats(list(self._samples), live, self._name,
                          extra={"source": self.SOURCE})


def _foreground_fullscreen():
    """(PID de la fenêtre active, True si elle couvre tout son écran).

    Une fenêtre agrandie s'arrête à la barre des tâches ; un jeu, en plein écran
    comme en fenêtre sans bord, couvre l'écran entier. Le bureau lui-même
    couvre aussi l'écran, mais il appartient à explorer.exe, ignoré ailleurs.
    """
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        u32.GetForegroundWindow.restype = ctypes.c_void_p
        u32.MonitorFromWindow.restype = ctypes.c_void_p
        u32.MonitorFromWindow.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        u32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        u32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]

        hwnd = u32.GetForegroundWindow()
        if not hwnd:
            return 0, False
        pid = wintypes.DWORD(0)
        u32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        rect = wintypes.RECT()
        if not u32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return pid.value, False
        mon = u32.MonitorFromWindow(hwnd, 2)        # MONITOR_DEFAULTTONEAREST
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not mon or not u32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return pid.value, False
        m = info.rcMonitor
        full = (rect.left <= m.left and rect.top <= m.top
                and rect.right >= m.right and rect.bottom >= m.bottom)
        return pid.value, full
    except Exception:
        return 0, False


def _exe_to_game_name(exe):
    """'eFootball.exe' -> 'Efootball' (même présentation que RivaTuner)."""
    return RtssGameReader._game_name(exe.encode("latin-1", "ignore"))


class WindowsGameReader:
    """PresentMon d'abord, RivaTuner en secours (1.6.0 ; l'inverse en 1.5.x).

    Les deux tournent en parallèle, chacun avec sa propre session. On montre
    PresentMon tant qu'il mesure un jeu en direct ; sinon RivaTuner s'il en
    mesure un ; sinon la dernière session terminée, PresentMon en priorité.
    """

    def __init__(self):
        self._rtss = RtssGameReader()
        exe = find_presentmon()
        self._pm = PresentMonGameReader(exe) if exe else None

    def start(self):
        self._rtss.start()
        if self._pm is not None:
            self._pm.start()

    def stop(self):
        self._rtss.stop()
        if self._pm is not None:
            self._pm.stop()

    def sample(self):
        pm = self._pm.sample() if self._pm is not None else None
        if pm is not None and pm["live"]:
            return pm
        rtss = self._rtss.sample()
        if rtss is not None:
            rtss.setdefault("source", "RivaTuner")
            if rtss["live"]:
                return rtss
        return pm or rtss


def make_game_reader():
    """Lecteur de session adapté à la plateforme."""
    return WindowsGameReader() if IS_WINDOWS else MangoHudGameReader()
