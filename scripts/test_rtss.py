"""
Diagnostic RTSS 7.x — analyse différentielle pour trouver les champs qui bougent.
Lance pendant qu'un jeu tourne (RTSS doit afficher les FPS en overlay).
Le script prend 8 mesures à 1 seconde d'intervalle et montre quels offsets changent.
"""
import struct, ctypes, time, os

OUT = os.path.join(os.path.dirname(__file__), "test_rtss_result.txt")
lines = []

def log(s=""):
    print(s)
    lines.append(s)

FILE_MAP_READ = 0x0004
k32 = ctypes.windll.kernel32
k32.OpenFileMappingW.restype  = ctypes.c_void_p
k32.OpenFileMappingW.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
k32.MapViewOfFile.restype     = ctypes.c_void_p
k32.MapViewOfFile.argtypes    = [ctypes.c_void_p, ctypes.c_uint32,
                                  ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
k32.UnmapViewOfFile.restype   = ctypes.c_bool
k32.UnmapViewOfFile.argtypes  = [ctypes.c_void_p]
k32.CloseHandle.restype       = ctypes.c_bool
k32.CloseHandle.argtypes      = [ctypes.c_void_p]
k32.GetLastError.restype      = ctypes.c_uint32

log("=" * 70)
log(f"  Diagnostic RTSS 7.x — analyse différentielle  —  {time.strftime('%Y-%m-%d %H:%M:%S')}")
log("=" * 70)

# ── Helpers ──────────────────────────────────────────────────────────────────

def open_rtss():
    for mem_name in ("RTSSSharedMemoryV2", "Global\\RTSSSharedMemoryV2"):
        h = k32.OpenFileMappingW(FILE_MAP_READ, False, mem_name)
        if h:
            return h
    return None

def read_rtss(handle, total):
    ptr = k32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, total)
    if not ptr:
        return None
    data = bytes(ctypes.string_at(ptr, total))
    k32.UnmapViewOfFile(ptr)
    return data

# ── Ouvrir et lire le header ─────────────────────────────────────────────────

handle = open_rtss()
if not handle:
    log("ECHEC : mémoire partagée introuvable — RTSS ne tourne pas ?")
    with open(OUT, "w", encoding="utf-8") as f: f.write("\n".join(lines))
    input("\nEntrée pour quitter..."); raise SystemExit(1)

ptr = k32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, 64)
hdr = bytes(ctypes.string_at(ptr, 64))
k32.UnmapViewOfFile(ptr)

sig      = struct.unpack_from("<I", hdr, 0)[0]
entry_sz = struct.unpack_from("<I", hdr, 8)[0]
arr_off  = struct.unpack_from("<I", hdr, 12)[0]
arr_cnt  = struct.unpack_from("<I", hdr, 16)[0]
total    = arr_off + arr_cnt * entry_sz

log(f"Sig=0x{sig:08X}  entry_sz={entry_sz}  arr_off={arr_off}  arr_cnt={arr_cnt}")
log(f"Total={total} octets ({total/1024/1024:.2f} Mo)")

if total > 64 * 1024 * 1024:
    log("ECHEC : total trop grand")
    k32.CloseHandle(handle)
    input("\nEntrée pour quitter..."); raise SystemExit(1)

k32.CloseHandle(handle)

# ── Trouver l'entrée du jeu ─────────────────────────────────────────────────

log("\n" + "=" * 70)
log("Recherche de l'entrée du jeu...")
log("=" * 70)

def find_game_entry(data):
    GAME_KEYWORDS = [b"eFootball", b"game", b"steam", b".exe"]
    best_entry = None
    best_fps   = 0.0
    for i in range(arr_cnt):
        base = arr_off + i * entry_sz
        if base + entry_sz > len(data):
            break
        entry = data[base : base + min(entry_sz, 400)]
        pid = struct.unpack_from("<I", entry, 0)[0]
        if pid == 0:
            continue
        # Cherche le frame time RTSS 7.x à offset 312
        if len(entry) >= 316:
            ft = struct.unpack_from("<I", entry, 312)[0]
            if 500 < ft < 500_000:
                fps = 1_000_000.0 / ft
                if fps > best_fps:
                    best_fps   = fps
                    best_entry = i
    return best_entry, best_fps

data0 = None
handle = open_rtss()
data0  = read_rtss(handle, total)
k32.CloseHandle(handle)

game_idx, game_fps = find_game_entry(data0)
if game_idx is None:
    log("Aucun jeu détecté (dwFrameTime=0 partout). Lance le jeu + RTSS, puis relance ce script.")
    with open(OUT, "w", encoding="utf-8") as f: f.write("\n".join(lines))
    input("\nEntrée pour quitter..."); raise SystemExit(1)

base0 = arr_off + game_idx * entry_sz
entry0 = data0[base0 : base0 + entry_sz]
name0  = entry0[4:264].split(b"\x00")[0].decode("ascii", errors="replace").strip()
log(f"Jeu trouvé : entrée {game_idx} — {name0}")
log(f"FPS initial (offset 312) : {game_fps:.1f} FPS\n")

# ── Analyse différentielle : 8 lectures à 1 seconde d'intervalle ─────────────

log("=" * 70)
log("Analyse différentielle — 8 lectures à 1 s d'intervalle...")
log("(joue normalement pendant cette phase)")
log("=" * 70)

N_SAMPLES = 8
samples   = [entry0]  # déjà lue

for n in range(1, N_SAMPLES):
    time.sleep(1.0)
    h = open_rtss()
    d = read_rtss(h, total)
    k32.CloseHandle(h)
    e = d[base0 : base0 + entry_sz]
    # Vérifier que c'est toujours le même processus
    pid = struct.unpack_from("<I", e, 0)[0]
    ft  = struct.unpack_from("<I", e, 312)[0]
    fps = (1_000_000.0 / ft) if ft > 0 else 0
    log(f"  t={n:d}s  pid={pid}  offset+312={ft}µs → {fps:.1f} FPS")
    samples.append(e)

# ── Trouver tous les offsets qui changent ────────────────────────────────────

log("\n" + "=" * 70)
log("Offsets DWORD qui changent pendant les 8 secondes :")
log("=" * 70)

entry_bytes = min(entry_sz, 12416)
changing = {}  # offset → list of values

for off in range(0, entry_bytes - 3, 4):
    vals = []
    for s in samples:
        if off + 4 <= len(s):
            vals.append(struct.unpack_from("<I", s, off)[0])
    if len(set(vals)) > 1:
        changing[off] = vals

log(f"\n{len(changing)} offsets changent sur {entry_bytes} octets analysés.\n")

# Trier par amplitude de variation (max - min)
sorted_offs = sorted(changing.items(), key=lambda x: max(x[1]) - min(x[1]), reverse=True)

log(f"{'offset':>7}  {'min':>12}  {'max':>12}  {'delta':>12}  {'interprétation'}")
log("-" * 75)

for off, vals in sorted_offs[:60]:   # top 60
    mn, mx = min(vals), max(vals)
    delta  = mx - mn
    fps_hint = ""
    if 500 < mn < 500_000 and 500 < mx < 500_000:
        fps_min = 1_000_000.0 / mx
        fps_max = 1_000_000.0 / mn
        fps_hint = f"  ← {fps_min:.0f}-{fps_max:.0f} FPS (frame time µs?)"
    elif 100_000 < delta < 10_000_000:
        fps_hint = f"  ← compteur croissant? (+{delta}/8s)"
    log(f"{off:>7d}  {mn:>12d}  {mx:>12d}  {delta:>12d}{fps_hint}")

# ── Focus sur offset 312 (notre offset actuel) ───────────────────────────────

log("\n" + "=" * 70)
log("Détail offset+312 (dwFrameTime actuel) :")
vals312 = [struct.unpack_from("<I", s, 312)[0] for s in samples if len(s) >= 316]
for i, v in enumerate(vals312):
    fps = (1_000_000.0 / v) if v > 0 else 0
    log(f"  t={i}s : {v}µs → {fps:.1f} FPS")

# ── Chercher un compteur de frames (croît de ~FPS/seconde) ──────────────────

log("\n" + "=" * 70)
log("Recherche d'un compteur de frames brut (doit augmenter de ~FPS/s) :")
log("=" * 70)

expected_delta_per_s = game_fps  # ~161 frames/s

for off, vals in sorted_offs:
    mn, mx = min(vals), max(vals)
    delta  = mx - mn
    # Le compteur monte de ~FPS par seconde, sur 7 intervalles = ~7*FPS
    expected_total = expected_delta_per_s * (N_SAMPLES - 1)
    if 0.5 * expected_total < delta < 2.0 * expected_total:
        # Vérifie que c'est bien monotone (ou presque)
        diffs = [vals[i+1] - vals[i] for i in range(len(vals)-1)]
        if all(d > 0 for d in diffs):
            log(f"  *** offset+{off:4d} : COMPTEUR MONOTONE — delta total={delta}, ~{delta/(N_SAMPLES-1):.0f}/s"
                f"  (attendu ~{expected_delta_per_s:.0f}/s)")

# ── Dump hex complet des 400 premiers octets à t=0 et t=7 ───────────────────

log("\n" + "=" * 70)
log("Hex dump des 400 premiers octets (t=0 vs t=7, différences en []) :")
log("=" * 70)

s0 = samples[0]
s7 = samples[-1]
for row in range(0, 400, 16):
    chunk0 = s0[row:row+16]
    chunk7 = s7[row:row+16]
    hex0 = " ".join(f"{b:02X}" for b in chunk0)
    hex7 = " ".join(f"{b:02X}" for b in chunk7)
    diff = "*" if chunk0 != chunk7 else " "
    log(f"  {row:04X} {diff} {hex0:<47}  |  {hex7}")

# ── Sauvegarder ──────────────────────────────────────────────────────────────

log("\n" + "=" * 70)
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
log(f"Résultats sauvegardés : {OUT}")
input("\nEntrée pour quitter...")
