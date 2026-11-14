#!/usr/bin/env python3
"""
CachyMonitor — moniteur système gaming (CPU / GPU / RAM / températures / FPS).

Une seule application pour Linux ET Windows : chaque lecteur choisit sa source
selon la plateforme, le reste (interface, thèmes, langues, calculs de
statistiques) est strictement commun. Ce fichier est le point d'entrée ; le code
vit dans le dossier cachymon/ (config, sensors, controllers, game, game_windows,
widgets...) et doit toujours être installé à côté de lui.

    Linux    : /proc, /sys (hwmon, manettes), nvidia-smi, logs CSV MangoHud
    Windows  : psutil, nvidia-smi, mémoire partagée MSI Afterburner et RTSS,
               manettes via XInput et HID brut

Dépendances : PySide6 partout, plus psutil sous Windows uniquement.
Aucune autre librairie : les graphes sont dessinés au QPainter.

--------------------------------------------------------------------------
MATÉRIEL — ce qui est réellement testé
--------------------------------------------------------------------------
Le code vise tous les matériels, mais il n'a été VÉRIFIÉ que sur :

    CPU AMD Ryzen 5 5600 (k10temp) + GPU NVIDIA RTX 3060 (nvidia-smi)
      · CachyOS / KDE Plasma / Wayland
      · Windows 11 Pro 24H2 + MSI Afterburner / RivaTuner (RTSS 7.x)

Écrit d'après la documentation mais JAMAIS EXÉCUTÉ sur le matériel
correspondant :

  * température CPU Intel      -> capteur « coretemp »        [Linux]
  * GPU AMD (Radeon)           -> pilote amdgpu via /sys      [Linux]
  * GPU Intel (i915 / xe)      -> partiel, /sys               [Linux]
  * GPU non-NVIDIA sous Windows -> capteurs Afterburner       [Windows]
  * manette Xbox sous Windows  -> XInput                     [Windows]

Si vous testez sur l'une de ces configurations, les retours sont les
bienvenus : ouvrez une « issue » avec la sortie de `scripts/hw-report.sh`
(ou simplement une capture de l'application).
https://github.com/YOUNES-2-wq/cachymonitor/issues
--------------------------------------------------------------------------
"""


import os
import sys
import time
# Le dossier de ce fichier d'abord : le paquet cachymon/ y est installe a cote, y compris
# quand Python est lance en mode isole (-I) ou via un lien symbolique.
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout, QCheckBox, QSpinBox, QComboBox, QToolButton, QListView
from cachymon.config import DEFAULT_FPS_TARGET, DEFAULT_INTERVAL_MS, IS_WINDOWS, _as_bool, asset_dir
from cachymon.i18n import DEFAULT_LANG, LANG_LABELS, LANG_MODES, set_language, tr
from cachymon.sampler import Sampler
from cachymon.sensors import read_cpu_name, read_ram_name
from cachymon.theme import DEFAULT_THEME, THEME_LABELS, THEME_MODES, col, resolve_theme, set_palette, temp_role
from cachymon.widgets import ControllerPanel, GamePanel, GaugeCard


APP_VERSION = "1.5.2"


# ----------------------------------------------------------------------------- #
#  Menu déroulant
# ----------------------------------------------------------------------------- #

class DropDownComboBox(QComboBox):
    """Liste déroulante qui s'ouvre TOUJOURS sous le champ, sur un fond opaque.

    Laissés au style du bureau, Breeze et Adwaita affichent la liste comme un
    menu centré sur l'entrée courante : choisie la dernière entrée, la liste
    s'ouvre vers le haut — déroutant — et son fond translucide laisse voir le
    bureau à travers. La règle QSS « combobox-popup: 0 » impose la liste
    déroulante classique ; les deux réglages ci-dessous rendent son conteneur
    opaque. Ils sont reposés à chaque ouverture car le style du bureau les
    réapplique après coup (et seule une fenêtre encore invisible peut changer
    de transparence).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setView(QListView())

    def showPopup(self):
        popup = self.view().window()
        popup.setAttribute(Qt.WA_TranslucentBackground, False)
        popup.setAutoFillBackground(True)
        super().showPopup()


# ----------------------------------------------------------------------------- #
#  Fenêtre principale
# ----------------------------------------------------------------------------- #

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CachyMonitor")
        self.resize(560, 720)
        self.theme_mode = DEFAULT_THEME
        self.lang_mode = DEFAULT_LANG

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        # En-tête : titre + bouton qui déplie les réglages
        header = QHBoxLayout()
        title = QLabel("CachyMonitor")
        title.setObjectName("appTitle")
        header.addWidget(title)
        header.addStretch()

        self.opt_button = QToolButton()
        self.opt_button.setObjectName("optButton")
        self.opt_button.setText("⚙  Options")
        self.opt_button.setCheckable(True)
        self.opt_button.setCursor(Qt.PointingHandCursor)
        header.addWidget(self.opt_button)
        root.addLayout(header)

        # Le panneau existe avant qu'on branche le signal : _toggle_options
        # planterait s'il se déclenchait sur un self.options pas encore créé.
        self._build_options()
        root.addWidget(self.options)
        self.opt_button.toggled.connect(self._toggle_options)

        # Cartes
        grid = QGridLayout()
        grid.setSpacing(14)

        self.cpu = GaugeCard("CPU", "cpu")
        self.gpu = GaugeCard("GPU", "gpu")
        self.ram = GaugeCard("RAM", "ram")
        self.vram = GaugeCard("VRAM", "vram")
        self.game = GamePanel()
        self.controllers = ControllerPanel()

        grid.addWidget(self.cpu, 0, 0)
        grid.addWidget(self.gpu, 0, 1)
        grid.addWidget(self.ram, 1, 0)
        grid.addWidget(self.vram, 1, 1)
        grid.addWidget(self.controllers, 2, 0, 1, 2)
        grid.addWidget(self.game, 3, 0, 1, 2)
        grid.setRowStretch(3, 1)
        root.addLayout(grid, 1)

        # Noms matériel statiques (lus une seule fois)
        self.cpu.hw.setText(read_cpu_name())
        self.ram.hw.setText(read_ram_name())

        self.status = QLabel(tr("Starting…"))
        self.started = False   # passe à True au 1er échantillon (statut réel)
        self.status.setObjectName("status")
        root.addWidget(self.status)

        # Réglages mémorisés (intervalle, cible FPS, thème, langue, "au-dessus",
        # géométrie). Les textes sont posés avec la langue par défaut pendant la
        # construction : retext() les repose dans celle qui a été mémorisée.
        self._load_settings()
        self.retext()
        self.apply_theme()

        # Suivi du thème du bureau quand le mode « Système » est choisi.
        QApplication.instance().styleHints().colorSchemeChanged.connect(
            self._on_system_theme_changed
        )

        # Sampler
        self.sampler = Sampler()
        self.sampler.interval_ms = self.interval.value()
        self.sampler.sampled.connect(self.on_sample)
        self.sampler.start()

    # -- panneau Options ---------------------------------------------------- #
    def _build_options(self):
        """Zone de réglages dépliable. Repliée par défaut : l'écran reste dédié
        aux mesures, qui sont la raison d'être de l'application."""
        self.options = QFrame()
        self.options.setObjectName("options")
        self.options.setVisible(False)

        grid = QGridLayout(self.options)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self.interval = QSpinBox()
        self.interval.setRange(200, 5000)
        self.interval.setSingleStep(100)
        self.interval.setValue(DEFAULT_INTERVAL_MS)
        self.interval.setSuffix(" ms")
        self.interval.setToolTip(tr("Measurement refresh rate"))
        self.interval.valueChanged.connect(self._set_interval)

        self.fps_target = QSpinBox()
        self.fps_target.setRange(30, 500)
        self.fps_target.setSingleStep(5)
        self.fps_target.setValue(DEFAULT_FPS_TARGET)
        self.fps_target.setToolTip(
            tr("Scales the FPS colours and marks the frametime graph")
        )

        self.theme = DropDownComboBox()
        for mode in THEME_MODES:
            self.theme.addItem(tr(THEME_LABELS[mode]), mode)
        self.theme.setToolTip(tr("« System » follows the desktop light/dark setting"))
        self.theme.currentIndexChanged.connect(self._set_theme)

        self.lang = DropDownComboBox()
        for mode in LANG_MODES:
            self.lang.addItem(tr(LANG_LABELS[mode]), mode)
        self.lang.setToolTip(tr("« System » follows the desktop language"))
        self.lang.currentIndexChanged.connect(self._set_language)

        self.ontop = QCheckBox(tr("Always on top"))
        self.ontop.toggled.connect(self._toggle_ontop)

        self.l_interval = QLabel(tr("Interval"))
        self.l_fps = QLabel(tr("FPS target"))
        self.l_theme = QLabel(tr("Theme"))
        self.l_lang = QLabel(tr("Language"))

        grid.addWidget(self.l_interval, 0, 0)
        grid.addWidget(self.interval, 0, 1)
        grid.addWidget(self.l_fps, 0, 2)
        grid.addWidget(self.fps_target, 0, 3)
        grid.addWidget(self.l_theme, 1, 0)
        grid.addWidget(self.theme, 1, 1)
        grid.addWidget(self.l_lang, 1, 2)
        grid.addWidget(self.lang, 1, 3)
        grid.addWidget(self.ontop, 2, 0, 1, 4)
        grid.setColumnStretch(4, 1)

    def _toggle_options(self, shown):
        self.options.setVisible(shown)

    # -- langue ------------------------------------------------------------- #
    def _set_language(self, _index):
        self.lang_mode = self.lang.currentData()
        set_language(self.lang_mode)
        self.retext()

    def retext(self):
        """Repose tous les textes fixes de l'interface dans la langue active.

        Les textes qui dépendent des mesures (statut, goulot, unités des jauges)
        ne sont pas touchés ici : ils sont réécrits au prochain échantillon, donc
        au plus tard après un intervalle de rafraîchissement.
        """
        self.interval.setToolTip(tr("Measurement refresh rate"))
        self.fps_target.setToolTip(
            tr("Scales the FPS colours and marks the frametime graph")
        )
        self.l_interval.setText(tr("Interval"))
        self.l_fps.setText(tr("FPS target"))
        self.l_theme.setText(tr("Theme"))
        self.l_lang.setText(tr("Language"))
        self.ontop.setText(tr("Always on top"))
        self.theme.setToolTip(tr("« System » follows the desktop light/dark setting"))
        self.lang.setToolTip(tr("« System » follows the desktop language"))

        # Les entrées des listes : on réécrit le libellé sans toucher au choix.
        for combo, labels in ((self.theme, THEME_LABELS), (self.lang, LANG_LABELS)):
            for i in range(combo.count()):
                combo.setItemText(i, tr(labels[combo.itemData(i)]))

        self.game.retext()
        self.controllers.retext()
        # Capacité RAM : lue une seule fois au démarrage, son unité est traduite.
        self.ram.hw.setText(read_ram_name())
        if not self.started:
            self.status.setText(tr("Starting…"))

    # -- thème -------------------------------------------------------------- #
    def _set_theme(self, _index):
        self.theme_mode = self.theme.currentData()
        self.apply_theme()

    def _on_system_theme_changed(self, _scheme):
        """Le bureau est passé du clair au sombre (ou l'inverse)."""
        if self.theme_mode == "systeme":
            self.apply_theme()

    def apply_theme(self):
        """Bascule la palette et redessine tout, sans redémarrer l'application :
        l'historique des courbes et la session de jeu en cours sont conservés."""
        set_palette(resolve_theme(self.theme_mode))
        app = QApplication.instance()
        app.setPalette(build_palette())
        app.setStyleSheet(build_style())
        # Le QSS ne couvre pas les couleurs posées en ligne ni le QPainter.
        for card in (self.cpu, self.gpu, self.ram, self.vram, self.game,
                     self.controllers):
            card.retheme()
        self.update()

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
        power = d.get("cpu_power")
        line = f"{freq} · {power:.0f} W" if power else freq
        self.cpu.update_value(d["cpu_pct"], f"{d['cpu_pct']:.0f}%",
                              f"{line}\n{ttxt}", temp_role(t))

        # GPU
        gpu_name = d["gpu_name"].replace("NVIDIA ", "")
        if self.gpu.hw.text() != gpu_name:
            self.gpu.hw.setText(gpu_name)
            self.vram.hw.setText(gpu_name)
        gt = d["gpu_temp"]
        gttxt = f"{gt:.0f}°C" if gt is not None else "—"
        pw = f"{d['gpu_power']:.0f} W" if d["gpu_power"] else "—"
        self.gpu.update_value(d["gpu_pct"], f"{d['gpu_pct']:.0f}%",
                              f"{pw}\n{gttxt}", temp_role(gt))

        # RAM
        self.ram.update_value(d["ram_pct"], f"{d['ram_pct']:.0f}%",
                              f"{d['ram_used']:.1f} / {d['ram_total']:.1f} {tr('GiB')}")

        # VRAM
        vt, vu = d["vram_total"], d["vram_used"]
        vpct = (vu / vt * 100) if vt else 0
        self.vram.update_value(vpct, f"{vpct:.0f}%",
                               f"{vu/1024:.1f} / {vt/1024:.1f} {tr('GiB')}")

        # Manettes
        self.controllers.update_controllers(d.get("controllers", []))

        # Session de jeu (MangoHud)
        g = d.get("game")
        if g is None:
            self.game.clear()
        else:
            self.game.update_game(g, self.fps_target.value())

        self.started = True
        self.status.setText(
            tr("Updated every {ms} ms").format(ms=self.sampler.interval_ms)
            + f" · {time.strftime('%H:%M:%S')}"
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

        # Thème : le mode est appliqué juste après, par apply_theme().
        mode = s.value("theme", DEFAULT_THEME)
        if mode not in THEME_MODES:
            mode = DEFAULT_THEME
        self.theme_mode = mode
        self.theme.blockSignals(True)
        self.theme.setCurrentIndex(THEME_MODES.index(mode))
        self.theme.blockSignals(False)

        # Langue : les textes sont reposés juste après, par retext().
        lang = s.value("language", DEFAULT_LANG)
        if lang not in LANG_MODES:
            lang = DEFAULT_LANG
        self.lang_mode = lang
        set_language(lang)
        self.lang.blockSignals(True)
        self.lang.setCurrentIndex(LANG_MODES.index(lang))
        self.lang.blockSignals(False)

        # QSettings renvoie les booléens en texte selon le backend.
        if _as_bool(s.value("options_open", False)):
            self.opt_button.setChecked(True)

        ontop = _as_bool(s.value("ontop", False))
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
        s.setValue("theme", self.theme_mode)
        s.setValue("language", self.lang_mode)
        s.setValue("options_open", self.opt_button.isChecked())
        s.setValue("ontop", self.ontop.isChecked())
        s.setValue("geometry", self.saveGeometry())

    def closeEvent(self, e):
        self._save_settings()
        self.sampler.stop()
        super().closeEvent(e)


def build_palette():
    """Palette Qt du thème actif.

    Indispensable : les éléments dessinés par le style du bureau (flèches des
    compteurs, coche des cases, flèche du menu déroulant) ignorent la feuille de
    style et suivent la palette. Sans ça, un bureau en thème sombre les dessine
    en clair — donc invisibles — dès qu'on passe CachyMonitor en thème clair.
    """
    pal = QPalette()
    bg, card = QColor(col("bg")), QColor(col("card"))
    text, muted = QColor(col("text")), QColor(col("muted"))
    for role, c in (
        (QPalette.Window, bg),
        (QPalette.WindowText, text),
        (QPalette.Base, card),
        (QPalette.AlternateBase, bg),
        (QPalette.Text, text),
        (QPalette.Button, card),
        (QPalette.ButtonText, text),
        (QPalette.ToolTipBase, card),
        (QPalette.ToolTipText, text),
        (QPalette.PlaceholderText, muted),
        (QPalette.Highlight, QColor(col("cpu"))),
        (QPalette.HighlightedText, card),
    ):
        pal.setColor(role, c)
    pal.setColor(QPalette.Disabled, QPalette.Text, muted)
    pal.setColor(QPalette.Disabled, QPalette.WindowText, muted)
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, muted)
    return pal


def build_style():
    """Feuille de style du thème actif (regénérée à chaque changement)."""
    return f"""
QWidget {{ background: {col('bg')}; color: {col('text')}; font-family: 'Inter','Noto Sans',sans-serif; font-size: 13px; }}
/* Sans fond transparent, chaque libellé peint un rectangle de la couleur du
   fond général, visible comme une bande sur les cartes. */
QLabel, QCheckBox {{ background: transparent; }}
#appTitle {{ font-size: 20px; font-weight: 700; }}
#card {{ background: {col('card')}; border-radius: 14px; }}
#cardTitle {{ color: {col('muted')}; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; }}
#cardHw {{ font-size: 11px; font-weight: 600; }}
#cardValue {{ font-size: 26px; font-weight: 700; }}
#cardSub {{ color: {col('muted')}; font-size: 12px; }}
#status {{ color: {col('muted')}; font-size: 11px; }}
#options {{ background: {col('card')}; border-radius: 12px; }}
#optButton {{ background: {col('card')}; color: {col('muted')}; border: 1px solid {col('border')}; border-radius: 8px; padding: 5px 12px; font-weight: 600; }}
#optButton:hover {{ color: {col('text')}; }}
#optButton:checked {{ color: {col('cpu')}; border-color: {col('cpu')}; }}
QSpinBox, QComboBox {{ background: {col('card')}; color: {col('text')}; border: 1px solid {col('border')}; border-radius: 6px; padding: 2px 6px; }}
/* combobox-popup: 0 => vraie liste déroulante sous le champ, au lieu du menu
   centré sur l'entrée courante que dessinent Breeze et Adwaita. */
QComboBox {{ combobox-popup: 0; }}
QComboBox QAbstractItemView {{ background-color: {col('card')}; color: {col('text')}; border: 1px solid {col('border')}; outline: 0; selection-background-color: {col('cpu')}; selection-color: {col('card')}; }}
/* Le conteneur du menu déroulant est translucide chez certains styles : on lui
   redonne un fond plein, sinon le bureau se voit à travers la liste. */
QComboBox QAbstractItemView::item {{ padding: 3px 6px; }}
QComboBox QListView {{ background-color: {col('card')}; }}
QCheckBox {{ color: {col('muted')}; spacing: 8px; }}
/* L'indicateur est dessiné ici plutôt que laissé au style natif : sous Windows,
   celui-ci suit le thème du SYSTÈME et non celui de l'application, si bien qu'un
   bureau en sombre dessinait une case blanche — invisible — dès que CachyMonitor
   passait en thème clair. Le remplissage plein signale l'état coché. */
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {col('border')}; border-radius: 4px; background: {col('bg')}; }}
QCheckBox::indicator:hover {{ border-color: {col('cpu')}; }}
QCheckBox::indicator:checked {{ background: {col('cpu')}; border-color: {col('cpu')}; }}
"""


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("CachyMonitor")
    # Windows n'affiche pas les SVG dans la barre des tâches : le .ico d'abord.
    here = asset_dir()
    names = ("cachymonitor.ico", "cachymonitor.svg") if IS_WINDOWS else \
            ("cachymonitor.svg", "cachymonitor.ico")
    for name in names:
        icon_path = os.path.join(here, name)
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            break
    else:
        app.setWindowIcon(QIcon.fromTheme("utilities-system-monitor"))
    # La palette de départ est posée par MainWindow (apply_theme), qui connaît
    # le mode mémorisé.
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
