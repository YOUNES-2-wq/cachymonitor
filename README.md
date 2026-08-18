# CachyMonitor

# NOUVEAU — CachyMonitor est maintenant sur Windows 11

### Le même moniteur gaming, désormais sur Linux **et** sur Windows 11.

**[Télécharger l'installateur Windows (CachyMonitor-Setup.exe)](https://github.com/YOUNES-2-wq/cachymonitor/releases/latest)**

On double-clique, on installe, ça marche : ni Python ni PySide6 à installer, tout est
dans l'exécutable. Toutes les fonctions de la version Linux sont là — statistiques de
session (1 % low, 0.1 % low, moyenne), graphe de frametime, détection du goulot
d'étranglement CPU/GPU, thème clair/sombre et interface en français ou en anglais.

> **Deux logiciels sont nécessaires pour que tout fonctionne sous Windows :**
> **[MSI Afterburner](https://www.msi.com/Landing/afterburner)** et **RivaTuner (RTSS)**,
> livré avec lui. Les deux sont gratuits. Sans eux, l'application démarre et affiche
> l'usage CPU, la RAM et le GPU, mais **la température, la consommation et les FPS
> restent vides**. Windows n'expose pas ces capteurs comme le fait le noyau Linux :
> CachyMonitor lit donc ceux d'Afterburner.
> [Détails](#prérequis--msi-afterburner-et-rivatuner)

> **Version Windows testée sur une seule machine.** AMD Ryzen 5 5600 + NVIDIA RTX 3060
> sous Windows 11 Pro 24H2, et rien d'autre. Sur une Radeon, un CPU Intel ou un GPU
> intégré, le code existe mais **n'a jamais été exécuté**. Si vous l'essayez, dites-moi
> ce que ça donne : [Discussions](https://github.com/YOUNES-2-wq/cachymonitor/discussions).
> C'est le seul moyen que j'aie de savoir si ça marche ailleurs que chez moi.

[Aller directement à l'installation Windows](#installation-sur-windows-11)

---

Moniteur système léger : **CPU, GPU, RAM, VRAM, températures et FPS**, avec graphes temps réel. Un seul fichier Python qui tourne sur **Linux et Windows 11**, une seule dépendance (PySide6).

> ℹ️ Projet communautaire indépendant, créé par un utilisateur de CachyOS. **Non affilié à l'équipe officielle de CachyOS** — le nom traduit simplement l'affection pour la distribution.

![CachyMonitor en thème sombre](docs/screenshot.png)

*Jauges CPU / GPU / RAM / VRAM avec températures et courbes de tendance, et en bas les statistiques de session : FPS, 1 % low, 0.1 % low, frametime et goulot d'étranglement CPU/GPU.*

![CachyMonitor en thème clair, panneau Options ouvert](docs/screenshot-clair.png)

*Thème clair, panneau Options ouvert : intervalle de rafraîchissement, cible FPS, thème (clair / sombre / système), langue et affichage au-dessus des autres fenêtres.*

> 🌍 **Langue** — l'interface suit par défaut la langue du système (`LANG`/`LC_ALL` sous
> Linux, la locale Windows sinon) :
> **français** si le bureau l'est, **anglais** partout ailleurs. Elle se change aussi
> à la main, à chaud, dans le panneau **⚙ Options → Langue** (Système / English /
> Français) ; le choix est mémorisé. Ajouter une langue = ajouter une entrée au
> dictionnaire `TRANSLATIONS` en haut de `cachymonitor.py`, les contributions sont
> bienvenues.

## Pourquoi CachyMonitor ?

Je suis un gamer et j'aime jouer à plusieurs jeux sur CachyOS. Je cherchais une application capable de monitorer mon matériel et de me donner un maximum d'informations sur le comportement de mes composants pendant le jeu — mais je n'ai trouvé aucun moniteur système pensé spécialement pour les jeux. J'ai donc décidé de créer le mien.

Comme je n'ai aucune formation de développeur, j'ai sollicité l'aide de mon ami IA, Claude, qui m'a énormément aidé. Le résultat a été tellement bluffant que j'ai eu envie de partager cette application avec toute personne qui souhaite l'essayer.

## Une première du genre 🚀

CachyMonitor s'appuie sur **[MangoHud](https://github.com/flightlessmango/MangoHud)**,
l'outil de référence qui enregistre les performances en jeu sous Linux. Mais là où
MangoHud affiche un **overlay par-dessus le jeu**, CachyMonitor va plus loin : il
**transforme ces logs en véritables statistiques de session**, dans une fenêtre à part.

À ma connaissance, c'est **la première application de ce genre** — une fenêtre
compagnon, distincte du jeu, qui réunit dans une seule interface visuelle :

- les **statistiques de session calculées** — 1 % low, 0,1 % low, moyenne, pics de
  frametime (micro-saccades) et **goulot d'étranglement CPU vs GPU** ;
- les **jauges de composants en direct** — CPU, GPU, RAM, VRAM, fréquences,
  consommation et températures, avec courbes de tendance ;
- le tout **sans overlay** qui s'affiche par-dessus le jeu, dans une appli légère
  (un seul fichier Python, une seule dépendance) ;
- en **thème clair ou sombre**, au choix ou en suivant automatiquement le bureau.

Les briques existaient déjà (MangoHud, Goverlay…), mais personne ne les avait
assemblées en un **tableau de bord compagnon pensé pour le jeu**. C'est toute
l'idée de CachyMonitor : ne pas réinventer la mesure, mais la rendre **lisible et
analysable**. 🙏 Merci à l'équipe de MangoHud, sans qui rien de tout ça ne serait possible.

## Installation sur Windows 11

**[Télécharger CachyMonitor-Setup.exe](https://github.com/YOUNES-2-wq/cachymonitor/releases/latest)**,
puis double-cliquer. L'assistant propose d'installer pour tous les utilisateurs ou pour
vous seul, crée les raccourcis (bureau + menu Démarrer) et s'enlève proprement depuis
*Paramètres → Applications*. **Python n'est pas nécessaire** : tout est dans l'exécutable.

> **Windows peut afficher un avertissement bleu « Windows a protégé votre ordinateur ».**
> C'est normal et ce n'est pas un virus : l'installateur n'est pas signé numériquement,
> car un certificat coûte plusieurs centaines d'euros par an pour un projet gratuit.
> Cliquez sur **Informations complémentaires** puis **Exécuter quand même**.
> Cet avertissement dépend de la réputation du fichier chez Microsoft : il apparaît
> surtout sur les téléchargements récents et se raréfie avec le temps. Le code source
> est entièrement lisible ici, et vous pouvez reconstruire l'installateur vous-même
> (voir plus bas).

### Prérequis : MSI Afterburner et RivaTuner

**À lire avant de s'étonner que des valeurs soient vides.** Sous Windows, CachyMonitor
ne mesure pas le matériel lui-même : le système n'expose pas les capteurs comme le fait
le noyau Linux, où tout se lit dans `/sys`. L'application s'appuie donc sur
**MSI Afterburner**, que la plupart des joueurs font déjà tourner.

| Pour obtenir | Il faut |
|---|---|
| Température, consommation et fréquence réelle du CPU | **[MSI Afterburner](https://www.msi.com/Landing/afterburner)** (gratuit) |
| FPS et statistiques de session (1 % low, 0.1 % low…) | **RivaTuner (RTSS)**, installé automatiquement avec Afterburner |
| Usage CPU, RAM, nom du processeur | rien, ça marche partout |
| GPU, VRAM, température GPU | rien sur NVIDIA (`nvidia-smi`) ; Afterburner sinon |

**Ce qu'il faut faire :** installer Afterburner, le laisser tourner (il démarre RTSS
tout seul), et c'est fini. Aucun réglage à faire dans CachyMonitor.

**Sans Afterburner**, l'application démarre et reste utilisable : usage CPU, RAM, GPU et
VRAM s'affichent normalement. En revanche la température, la consommation et les FPS
restent à `—`. Un repli existe pour la seule température, via
[LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor).

> Les chiffres viennent **de la même source que l'OSD de RivaTuner** : le FPS affiché par
> CachyMonitor est exactement celui que vous voyez en jeu, sans écart de calcul.

### Reconstruire l'installateur soi-même

```powershell
python -m pip install pyinstaller pyside6 psutil
winget install JRSoftware.InnoSetup
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

Le résultat apparaît dans `dist\`.

### Lancer sans installer (depuis les sources)

```powershell
python -m pip install pyside6 psutil
python cachymonitor.py
```

## Installation sur Linux

> **CachyMonitor fonctionne sur n'importe quelle distribution Linux** (Arch,
> CachyOS, Fedora, Ubuntu, Debian, openSUSE, Pop!\_OS…). Il ne lit que des sources
> standard du noyau (`/proc`, `/sys`, `hwmon`), `nvidia-smi` et les logs MangoHud :
> rien n'est spécifique à une distribution. La seule différence entre distros, c'est
> la manière d'installer la dépendance (**PySide6**).
>
> - **Distros basées sur Arch** (CachyOS, Manjaro, EndeavourOS…) → installation en une
>   commande via l'**AUR** (ci-dessous).
> - **Toutes les autres distros** → installation manuelle depuis Git (section plus bas).
>
> **X11 comme Wayland** — aucune donnée ne transite par le serveur d'affichage, et
> Qt6 gère les deux. Testé sur les deux backends. Seule différence à connaître :
> l'option « au-dessus des autres fenêtres » est toujours respectée sous X11, alors
> que beaucoup de compositeurs Wayland ignorent cette demande venant d'une
> application — ce n'est pas un bug de CachyMonitor.

### Depuis l'AUR (recommandé, distros Arch)

[![AUR version](https://img.shields.io/aur/version/cachymonitor?label=AUR&color=1793d1&cacheSeconds=600)](https://aur.archlinux.org/packages/cachymonitor)

Sur CachyOS / Arch, avec un assistant AUR — par exemple `paru` :

```sh
paru -S cachymonitor
```

ou `yay` :

```sh
yay -S cachymonitor
```

Puis lance **CachyMonitor** depuis ton menu d'applications, ou la commande `cachymonitor`.

### Manuellement, sur n'importe quelle distribution

Fonctionne partout : il suffit de **Python 3** (déjà présent sur toute distro) et de
**PySide6**.

**1. Installe PySide6** avec le gestionnaire de paquets de ta distro :

```sh
# Arch / CachyOS / Manjaro
sudo pacman -S pyside6

# Fedora
sudo dnf install python3-pyside6

# Ubuntu / Debian / Pop!_OS / Mint
# Debian découpe PySide6 en un paquet par module Qt : il n'existe pas de paquet
# « python3-pyside6 » global. CachyMonitor n'a besoin que de ces trois-là.
sudo apt install python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets

# openSUSE
sudo zypper install python3-PySide6
```

> Si PySide6 n'est pas packagé sur ta distro, tu peux toujours l'installer avec pip
> (idéalement dans un environnement virtuel) : `pip install PySide6`.

**2. Clone le dépôt :**

```sh
git clone https://github.com/YOUNES-2-wq/cachymonitor.git
```

**3. Lance l'application :**

```sh
python3 cachymonitor/cachymonitor.py
```

> Optionnel selon ton matériel : `mangohud` (statistiques en jeu), `nvidia-utils`
> (GPU NVIDIA), `pciutils` (nom du GPU), `dmidecode` (type/vitesse RAM). Chacun de ces
> paquets s'installe de la même façon selon ta distro (`dnf`, `apt`, `zypper`…).

## Sources des données

Un seul fichier, deux jeux de sources : `IS_WINDOWS` aiguille chaque lecteur, tout le
reste (interface, thèmes, langues, calcul des statistiques) est strictement commun.

| Métrique       | Linux                                 | Windows 11                                   |
|----------------|---------------------------------------|----------------------------------------------|
| CPU usage/cœur | `/proc/stat`                          | psutil                                       |
| CPU fréquence  | `scaling_cur_freq`                    | MSI Afterburner *(fréquence réelle, boost)*  |
| CPU temp       | hwmon `k10temp` / `coretemp`          | Afterburner, puis LibreHardwareMonitor       |
| CPU conso      | —                                     | Afterburner                                  |
| RAM            | `/proc/meminfo` + `dmidecode`         | psutil + `Win32_PhysicalMemory`              |
| GPU / VRAM     | `nvidia-smi`, `amdgpu`, `i915`        | `nvidia-smi`, puis capteurs Afterburner      |
| FPS / session  | logs CSV de **MangoHud**              | **RivaTuner (RTSS)**, relevé toutes les 100 ms |

> Pourquoi 100 ms sous Windows : les « lows » ont besoin de beaucoup de points. À une
> mesure par seconde, le 0.1 % low se calculerait sur 60 valeurs par minute et ne
> voudrait plus rien dire. On échantillonne donc RTSS à la même cadence que le
> `log_interval` de MangoHud.

## Activer le FPS sous Linux (MangoHud)

> Sous Windows, rien à configurer : il suffit que **RivaTuner (RTSS)** tourne, ce qui
> est le cas dès qu'on lance MSI Afterburner.

Le FPS provient des logs MangoHud. Le plus simple : logging automatique.
Ajoute à `~/.config/MangoHud/MangoHud.conf` :

```ini
output_folder=~/.local/share/MangoHud/logs
autostart_log=1
log_interval=100
```

Puis lance un jeu avec MangoHud :

- **Steam** → propriétés du jeu → options de lancement : `mangohud %command%`
- **En direct** : `mangohud <jeu>`

Dès qu'un jeu tourne et écrit un log, CachyMonitor affiche le FPS automatiquement
(et repasse à « — » quelques secondes après la fermeture du jeu).

> Les dossiers cherchés sont configurables en haut du script (`FPS_LOG_DIRS`).

## Compatibilité matérielle

CachyMonitor vise **tout matériel**, mais tout n'est pas vérifié.

**Linux**

| | CPU | GPU |
|---|---|---|
| **AMD** | ✅ testé (`k10temp`) | ⚠️ écrit, non testé (`amdgpu` via `/sys`) |
| **Intel** | ⚠️ écrit, non testé (`coretemp`) | ⚠️ partiel, non testé (`i915`/`xe`) |
| **NVIDIA** | — | ✅ testé (`nvidia-smi`) |

**Windows 11**

| | CPU | GPU |
|---|---|---|
| **AMD** | ✅ testé (via Afterburner) | ⚠️ écrit, non testé (capteurs Afterburner) |
| **Intel** | ⚠️ écrit, non testé (via Afterburner) | ⚠️ écrit, non testé (capteurs Afterburner) |
| **NVIDIA** | — | ✅ testé (`nvidia-smi`) |

Sous Windows, l'usage CPU, la RAM et le nom du processeur ne dépendent d'aucun
matériel particulier et fonctionnent partout. À l'inverse, sur une carte non-NVIDIA
le repli Afterburner affichera la carte sous le nom générique « GPU » et laissera la
jauge VRAM à 0 % — Afterburner ne publie pas la VRAM totale.

**Configurations réellement vérifiées** : AMD Ryzen 5 5600 + NVIDIA RTX 3060, sous
CachyOS / KDE Plasma / Wayland **et** sous Windows 11 Pro 24H2 avec MSI Afterburner
et RivaTuner (RTSS 7.x).

Le reste est écrit d'après la documentation du noyau, sans matériel sous la main
pour l'exécuter. L'application ne plantera pas si un capteur manque : la valeur
concernée affiche simplement `—`.

À noter pour les GPU Intel : le taux d'occupation n'est pas exposé dans `/sys`
et demande `intel_gpu_top` avec les droits root. Seuls le nom, la température et
la fréquence sont donc lus. La VRAM est de la mémoire partagée, sans compteur
dédié.

### J'ai besoin de vous 🙏

J'ai créé CachyMonitor seul, et je n'ai **qu'une seule machine** pour le tester
(AMD Ryzen 5 5600 + NVIDIA RTX 3060). Autrement dit : **je n'ai aucune idée de la
façon dont l'application se comporte sur un autre matériel que le mien.**

Un Radeon, un CPU Intel, un GPU intégré… chaque configuration est différente, et
sans vous, ces cas resteront des angles morts. **C'est encore plus vrai pour la
version Windows 11, toute nouvelle** : elle n'a tourné que sur une seule machine. C'est vraiment là que j'ai besoin
de la communauté : **votre commentaire est le seul moyen de savoir comment l'app
réagit sur votre matériel**, et donc de l'améliorer pour tout le monde.

> **Sous Windows**, deux scripts de diagnostic sont fournis dans `scripts/` :
> `test_afterburner.py` liste tous les capteurs qu'Afterburner publie sur votre machine,
> et `test_rtss.py` inspecte la mémoire partagée de RivaTuner. Si une valeur reste vide
> chez vous, leur sortie me dira pourquoi bien mieux qu'une capture d'écran.

Pas besoin d'être développeur, ni de lancer quoi que ce soit. Un simple mot —
« chez moi tout marche » ou « la température GPU affiche `—` » — m'aide déjà
énormément. Racontez-moi votre config et ce que vous voyez, ça compte pour moi 🙂

**➡️ [Laisser un commentaire (Discussions)](https://github.com/YOUNES-2-wq/cachymonitor/discussions)**

<details>
<summary>💡 Optionnel : joindre un rapport matériel détaillé</summary>

Si vous voulez m'aider davantage, un petit script génère un rapport de vos
capteurs. Il est **en lecture seule**, ne demande **jamais** les droits root et
n'affiche **aucune** donnée personnelle — vous pouvez l'ouvrir et le lire avant
de le lancer :

```bash
cat scripts/hw-report.sh   # pour l'inspecter d'abord, en toute confiance
./scripts/hw-report.sh     # puis le lancer si vous le souhaitez
```

Collez sa sortie dans un commentaire ou une
[issue](https://github.com/YOUNES-2-wq/cachymonitor/issues).
</details>

## Licence

[MIT](LICENSE) — tu peux utiliser, modifier et redistribuer ce code
librement, à condition de conserver la mention de copyright.
