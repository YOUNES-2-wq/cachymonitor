# CachyMonitor

Moniteur système léger pour CachyOS : **CPU, GPU, RAM, VRAM, températures et FPS**, avec graphes temps réel. Un seul fichier Python, une seule dépendance (PySide6).

## Installation de la dépendance

```sh
sudo pacman -S pyside6
```

(Tout le reste — `nvidia-smi`, `sensors`, `mangohud` — est déjà présent sur ta machine.)

## Lancer

```sh
python3 ~/cachymonitor/cachymonitor.py
```

Pour l'avoir dans le menu KDE :

```sh
cp ~/cachymonitor/cachymonitor.desktop ~/.local/share/applications/
```

## Sources des données

| Métrique      | Source                                            |
|---------------|---------------------------------------------------|
| CPU usage/cœur| `/proc/stat`                                      |
| CPU fréquence | `/sys/.../cpufreq/scaling_cur_freq`               |
| CPU temp      | hwmon `k10temp` (Tctl)                             |
| RAM           | `/proc/meminfo`                                   |
| GPU / VRAM    | `nvidia-smi` (usage, temp, clock, power)          |
| FPS           | dernier log CSV de **MangoHud**                   |

## Activer le FPS (MangoHud)

Le FPS provient des logs MangoHud. Le plus simple : logging automatique.
Ajoute à `~/.config/MangoHud/MangoHud.conf` :

```ini
output_folder=/home/younescachy/.local/share/MangoHud/logs
autostart_log=1
log_interval=100
```

Puis lance un jeu avec MangoHud :

- **Steam** → propriétés du jeu → options de lancement : `mangohud %command%`
- **En direct** : `mangohud <jeu>`

Dès qu'un jeu tourne et écrit un log, CachyMonitor affiche le FPS automatiquement
(et repasse à « — » quelques secondes après la fermeture du jeu).

> Les dossiers cherchés sont configurables en haut du script (`FPS_LOG_DIRS`).
