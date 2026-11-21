"""CachyMonitor : barre de mise à jour (voir updater.py pour la mécanique).

Cachée tant qu'il n'y a rien de nouveau. Quand une release plus récente existe :
« Version X disponible » + bouton « Mettre à jour » -> téléchargement avec barre de
progression -> installateur silencieux -> l'appli se ferme, Inno Setup la relance.
"""

import sys
import threading

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QToolButton

from . import updater
from .debug import debug_exc
from .i18n import tr
from .pawnio import env_hardened, is_admin


def can_install_here():
    """L'installation automatique n'est permise que si elle ne profite pas d'un
    droit élevé : un process administrateur ne télécharge ni n'exécute rien depuis
    un dossier temporaire modifiable par l'utilisateur, sauf s'il est durci (son
    TEMP est alors celui de Windows, voir elevation.harden_environment). Hors exe
    empaqueté (sources), il n'y a pas d'installation à remplacer."""
    return bool(getattr(sys, "frozen", False)) and (not is_admin() or env_hardened())


class UpdateBar(QFrame):
    found = Signal(object)          # release plus récente (jamais None)
    quit_requested = Signal()       # l'installateur est lancé : l'appli doit se fermer
    dismissed = Signal(str)         # version écartée par l'utilisateur
    # Émis depuis les threads de travail ; Qt les range dans la file du thread de l'UI.
    _progress = Signal(int, int)
    _downloaded = Signal(str)
    _failed = Signal(str)
    _cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("updateBar")
        self.setVisible(False)
        self.release = None
        self._state = "offer"       # offer | downloading | error
        self._error = ""
        self._checking = False
        self._cancel = False

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 8, 8)
        row.setSpacing(10)
        self.label = QLabel()
        self.label.setObjectName("updateLabel")
        self.label.setWordWrap(True)
        row.addWidget(self.label, 1)
        self.progress = QProgressBar()
        self.progress.setObjectName("updateProgress")
        self.progress.setTextVisible(False)
        self.progress.setFixedSize(110, 8)
        row.addWidget(self.progress)
        self.button = QToolButton()
        self.button.setObjectName("updateButton")
        self.button.clicked.connect(self._on_button)
        row.addWidget(self.button)
        self.close_button = QToolButton()
        self.close_button.setObjectName("updateClose")
        self.close_button.setText("×")
        self.close_button.clicked.connect(self._dismiss)
        row.addWidget(self.close_button)

        self._progress.connect(self._on_progress)
        self._downloaded.connect(self._on_downloaded)
        self._failed.connect(self._on_failed)
        self._cancelled.connect(self._on_cancelled)

    # -- recherche -------------------------------------------------------- #
    def check(self, current):
        """Cherche une release plus récente que `current`, sans bloquer l'interface.
        Résultat par le signal `found`. Thread « daemon » : fermer l'appli pendant
        une requête réseau ne l'attend pas."""
        if self._checking:
            return
        self._checking = True

        def work():
            try:
                updater.purge_old_downloads()
                release = updater.check_for_update(current)
            finally:
                self._checking = False
            if release is not None:
                self.found.emit(release)

        threading.Thread(target=work, daemon=True).start()

    # -- affichage -------------------------------------------------------- #
    def offer(self, release):
        """Montre la barre pour cette release (sauf téléchargement en cours)."""
        if self._state != "downloading":
            self.release = release
            self._state = "offer"
            self.retext()
            self.setVisible(True)

    def hide_bar(self):
        if self._state != "downloading":
            self.setVisible(False)

    def retext(self):
        if self.release is None:
            return
        version = self.release.version
        downloading = self._state == "downloading"
        self.close_button.setToolTip(tr("Hide until the next version"))
        self.close_button.setVisible(not downloading)
        self.progress.setVisible(downloading)
        self.button.setVisible(True)
        self.button.setEnabled(True)
        if downloading:
            self.label.setText(tr("Downloading version {version}…").format(version=version))
            self.button.setText(tr("Cancel"))
        elif self._state == "error":
            self.label.setText(tr("The update failed ({reason}).").format(reason=self._error))
            self.button.setText(tr("Retry"))
        elif can_install_here() and self.release.installable:
            self.label.setText(tr("Version {version} is available.").format(version=version))
            self.button.setText(tr("Update now"))
        elif is_admin():
            # Pas de navigateur ni d'installation depuis un process administrateur.
            self.label.setText(tr("Version {version} is available. Restart CachyMonitor "
                                  "without administrator rights to update.").format(
                                      version=version))
            self.button.setVisible(False)
        else:
            self.label.setText(tr("Version {version} is available.").format(version=version))
            self.button.setText(tr("Open the download page"))

    # -- téléchargement --------------------------------------------------- #
    def _on_button(self):
        if self._state == "downloading":
            self.button.setEnabled(False)   # la requête réseau peut mettre du temps à s'arrêter
            self.cancel()
        elif can_install_here() and self.release.installable:
            self._start_download(self.release)
        else:
            QDesktopServices.openUrl(QUrl(self.release.page_url))

    def _start_download(self, release):
        self._state = "downloading"
        self._cancel = False
        self.progress.setRange(0, 0)        # indéterminé jusqu'au premier octet
        self.retext()

        def work():
            try:
                self._downloaded.emit(
                    updater.download(release, self._progress.emit, lambda: self._cancel))
            except updater.UpdateCancelled:
                self._cancelled.emit()
            except Exception as exc:
                debug_exc("mise à jour : téléchargement")
                self._failed.emit(str(exc))

        threading.Thread(target=work, daemon=True).start()

    def cancel(self):
        """Interrompt le téléchargement en cours (aussi à la fermeture de l'appli)."""
        self._cancel = True

    def _on_progress(self, done, total):
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(done)

    def _on_downloaded(self, path):
        self.label.setText(tr("Installing version {version}…").format(
            version=self.release.version))
        self.button.setVisible(False)
        self.progress.setVisible(False)
        if updater.launch_installer(path):
            self.quit_requested.emit()
        else:
            # UAC refusée ou installateur bloqué : on l'affiche, on laisse réessayer.
            self._on_failed(tr("Windows did not start the installer"))

    def _on_cancelled(self):
        self._state = "offer"       # annuler n'est pas un échec : retour à la proposition
        self.retext()

    def _on_failed(self, reason):
        self._state = "error"
        self._error = reason
        self.retext()

    def _dismiss(self):
        self.dismissed.emit(self.release.version)
        self.setVisible(False)
