#!/usr/bin/env bash
# Rapport matériel pour CachyMonitor.
#
# À lancer si vous testez CachyMonitor sur un matériel autre qu'AMD Ryzen +
# NVIDIA (la seule configuration où l'application a été vérifiée), puis à
# coller dans une issue :
#     https://github.com/YOUNES-2-wq/cachymonitor/issues
#
# Le script est en lecture seule : il ne modifie rien et n'a pas besoin de root.
# Il n'affiche aucune donnée personnelle (pas de nom d'utilisateur, pas de
# numéro de série) — relisez la sortie avant de la publier si vous le souhaitez.

echo "===== CachyMonitor — rapport matériel ====="
echo "date    : $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "noyau   : $(uname -r)"
echo "distrib : $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
echo "python  : $(python3 --version 2>&1)"
echo "pyside6 : $(python3 -c 'import PySide6; print(PySide6.__version__)' 2>&1 | tail -1)"

echo
echo "----- CPU -----"
grep -m1 "model name" /proc/cpuinfo | cut -d: -f2- | sed 's/^ *//'
echo "cœurs logiques : $(nproc)"

echo
echo "----- Capteurs hwmon (température CPU) -----"
for d in /sys/class/hwmon/hwmon*; do
    name=$(cat "$d/name" 2>/dev/null) || continue
    printf '%s (%s)\n' "$name" "$d"
    for f in "$d"/temp*_input; do
        [ -e "$f" ] || continue
        base=${f%_input}
        label=$(cat "${base}_label" 2>/dev/null || echo "-")
        val=$(cat "$f" 2>/dev/null)
        printf '    %-14s %-16s %s °C\n' "$(basename "$base")" "$label" \
               "$(awk -v v="$val" 'BEGIN{printf "%.1f", v/1000}')"
    done
done

echo
echo "----- Cartes graphiques -----"
command -v lspci >/dev/null && lspci -nn | grep -Ei 'vga|3d controller|display' || echo "(lspci absent)"

echo
echo "----- Attributs /sys par carte -----"
for dev in /sys/class/drm/card[0-9]*/device; do
    [ -f "$dev/vendor" ] || continue
    vendor=$(cat "$dev/vendor")
    case "$vendor" in
        0x10de) v="NVIDIA" ;;
        0x1002) v="AMD" ;;
        0x8086) v="Intel" ;;
        *)      v="inconnu" ;;
    esac
    echo "$dev  ->  $v ($vendor), pilote : $(basename "$(readlink "$dev/driver" 2>/dev/null)" 2>/dev/null)"
    for attr in gpu_busy_percent mem_info_vram_total mem_info_vram_used; do
        if [ -f "$dev/$attr" ]; then
            echo "    $attr = $(cat "$dev/$attr" 2>/dev/null)"
        else
            echo "    $attr : absent"
        fi
    done
    for hw in "$dev"/hwmon/hwmon*; do
        [ -d "$hw" ] || continue
        echo "    hwmon : $hw"
        for f in "$hw"/temp1_input "$hw"/power1_average "$hw"/power1_input "$hw"/freq1_input; do
            [ -e "$f" ] && echo "        $(basename "$f") = $(cat "$f" 2>/dev/null)"
        done
    done
done

echo
echo "----- nvidia-smi -----"
if command -v nvidia-smi >/dev/null; then
    nvidia-smi --query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total,clocks.gr,power.draw \
               --format=csv,noheader 2>&1
else
    echo "(absent — normal si vous n'avez pas de GPU NVIDIA)"
fi

echo
echo "----- Ce que CachyMonitor détecte réellement -----"
here=$(cd "$(dirname "$0")/.." && pwd)
python3 - "$here" <<'PY' 2>&1
import importlib.util, sys, os, time
base = sys.argv[1]
spec = importlib.util.spec_from_file_location("cm", os.path.join(base, "cachymonitor.py"))
cm = importlib.util.module_from_spec(spec); sys.modules["cm"] = cm
try:
    spec.loader.exec_module(cm)
except Exception as e:
    print("ÉCHEC du chargement :", e); sys.exit(1)

print("fichier température CPU :", cm.find_cpu_temp_file())
print("nom CPU                 :", cm.read_cpu_name())
print("nom RAM                 :", cm.read_ram_name())
c = cm.CpuReader(); time.sleep(0.3); d = c.sample()
print("CPU  -> %.1f %%  %s MHz  %s °C" % (
    d["cpu_pct"],
    round(d["cpu_freq"]) if d["cpu_freq"] else "?",
    round(d["cpu_temp"], 1) if d["cpu_temp"] is not None else "NON DÉTECTÉE"))
g = cm.read_gpu()
print("GPU  -> %s | %.0f %% | %s °C | %.0f/%.0f MiB | %s MHz | %s W" % (
    g["gpu_name"], g["gpu_pct"],
    round(g["gpu_temp"], 1) if g["gpu_temp"] is not None else "NON DÉTECTÉE",
    g["vram_used"], g["vram_total"],
    round(g["gpu_clock"]) if g["gpu_clock"] else "?",
    round(g["gpu_power"], 1) if g["gpu_power"] else "?"))
PY

echo
echo "===== fin du rapport ====="
