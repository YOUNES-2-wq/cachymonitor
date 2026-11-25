"""La fenêtre traite un relevé complet, avec et sans jeu (Qt hors écran).

Garde-fou ajouté après la séparation Windows/Linux : un bouton supprimé était encore
appelé par le panneau « EN JEU », qui plantait dès qu'un jeu était détecté (les FPS et
le nom du jeu ne s'affichaient plus, sans aucun message).
"""
import random

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def fenetre(tmp_path_factory):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    import cachymonitor
    app = QApplication.instance() or QApplication([])
    # Aucun thread de mesure : on envoie nos propres relevés. Le Sampler démarré par la
    # fenêtre faisait quitter Python avec un code d'erreur (la CI échouait malgré « 149
    # passed »), et son stop() lance PresentMon --terminate_existing_session, qui
    # couperait la session de l'appli installée sur le PC de test.
    mp = pytest.MonkeyPatch()
    mp.setattr(cachymonitor.Sampler, "start", lambda self: None)
    # Réglages dans un fichier à part : jamais ceux du registre.
    ini = str(tmp_path_factory.mktemp("reglages") / "test.ini")
    mp.setattr(cachymonitor, "app_settings", lambda: QSettings(ini, QSettings.IniFormat))
    win = cachymonitor.MainWindow()
    yield win
    win.update_bar.cancel()
    app.processEvents()
    mp.undo()


def _releve(jeu):
    return {"cpu_temp": 50.0, "cpu_freq": 4000, "cpu_pct": 40.0, "cpu_power": 55,
            "gpu_name": "NVIDIA X", "gpu_temp": 60.0, "gpu_power": 170, "gpu_pct": 97.0,
            "ram_pct": 70.0, "ram_used": 11.0, "ram_total": 16.0,
            "vram_total": 12000, "vram_used": 4000, "controllers": [], "game": jeu}


def test_releve_sans_jeu(fenetre):
    fenetre.on_sample(_releve(None))
    assert fenetre.started          # le relevé est allé jusqu'au bout (statut posé)


@pytest.mark.parametrize("n", [5, 700])
def test_releve_avec_jeu_affiche_fps_et_nom(fenetre, n):
    from cachymon.game import game_stats
    echantillons = [(i * 0.1, 120.0 + random.random() * 10, 8.0) for i in range(700)]
    jeu = game_stats(echantillons[:n], True, "Dawnwalker", extra={"source": "PresentMon"})
    fenetre.on_sample(_releve(jeu))
    assert fenetre.game.game.text() == "Dawnwalker"
    assert fenetre.game.s_fps.value.text() not in ("", "—")


def test_retour_au_jeu_absent(fenetre):
    fenetre.on_sample(_releve(None))
    assert fenetre.game.game.text() == ""


def _theme(win, mode):
    from cachymon.theme import THEME_MODES
    win.theme.setCurrentIndex(THEME_MODES.index(mode))


def _jeu():
    from cachymon.game import game_stats
    return game_stats([(i * 0.1, 120.0, 8.0) for i in range(50)], True, "Jeu")


def test_chaque_theme_avec_et_sans_jeu(fenetre):
    from cachymon.theme import THEME_MODES
    for mode in THEME_MODES:
        _theme(fenetre, mode)
        for releve in (_releve(_jeu()), _releve(None)):
            fenetre.on_sample(releve)
            assert fenetre.grab().toImage().pixelColor(2, 2).alpha() == 255, mode


def test_mode_compact_et_choix_des_cartes(fenetre):
    fenetre.compact.setChecked(True)
    fenetre.on_sample(_releve(_jeu()))
    assert fenetre.game.ft_graph.isHidden() and fenetre.controllers.isHidden()
    assert fenetre.game.status.isHidden()
    fenetre.on_sample(_releve(None))
    assert not fenetre.game.status.isHidden()      # aucun jeu : on dit pourquoi
    fenetre.compact.setChecked(False)
    assert not fenetre.game.ft_graph.isHidden() and not fenetre.controllers.isHidden()
    for box in fenetre.card_boxes.values():
        box.setChecked(False)
    fenetre.on_sample(_releve(_jeu()))
    assert fenetre.cpu.isHidden() and fenetre.game.isHidden()
    for box in fenetre.card_boxes.values():
        box.setChecked(True)
    assert not fenetre.cpu.isHidden() and not fenetre.game.isHidden()


def test_dialogues_opaques_avec_le_theme_claude(fenetre):
    from PySide6.QtWidgets import QMessageBox
    _theme(fenetre, "claude")
    box = QMessageBox(fenetre)
    box.setText("test")
    box.show()
    assert box.grab().toImage().pixelColor(6, 6).alpha() == 255
    box.hide()


def test_anneau_suit_les_petits_ecarts(fenetre):
    jauge = fenetre.vram.gauge
    jauge.set(33.0, "33%", "")
    for i in range(1, 200):
        jauge.set(33.0 + i * 0.033, "", "")
    assert abs(jauge.shown - jauge.percent) <= 0.5


def test_la_fenetre_reprend_sa_taille_apres_les_options(fenetre):
    from PySide6.QtWidgets import QApplication

    def attendre():
        for _ in range(5):
            QApplication.processEvents()

    fenetre.opt_button.setChecked(False)
    fenetre.compact.setChecked(False)
    fenetre.show()
    attendre()
    fenetre.resize(560, fenetre.minimumSizeHint().height() + 10)
    attendre()
    depart = fenetre.height()
    fenetre.opt_button.setChecked(True)
    fenetre.look_button.setChecked(True)
    attendre()
    assert fenetre.height() > depart
    fenetre.compact.setChecked(True)
    attendre()
    fenetre.look_button.setChecked(False)
    fenetre.opt_button.setChecked(False)
    attendre()
    assert fenetre.height() == fenetre.minimumSizeHint().height() < depart
    fenetre.opt_button.setChecked(True)
    attendre()
    fenetre.compact.setChecked(False)
    attendre()
    fenetre.opt_button.setChecked(False)
    attendre()
    assert fenetre.height() == depart
    fenetre.hide()
