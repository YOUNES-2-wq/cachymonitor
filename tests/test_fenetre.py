"""La fenêtre traite un relevé complet, avec et sans jeu (Qt hors écran).

Garde-fou ajouté après la séparation Windows/Linux : un bouton supprimé était encore
appelé par le panneau « EN JEU », qui plantait dès qu'un jeu était détecté (les FPS et
le nom du jeu ne s'affichaient plus, sans aucun message).
"""
import random

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def fenetre():
    from PySide6.QtWidgets import QApplication
    import cachymonitor
    app = QApplication.instance() or QApplication([])
    # Aucun thread de mesure : on envoie nos propres relevés. Le Sampler démarré par la
    # fenêtre faisait quitter Python avec un code d'erreur (la CI échouait malgré « 149
    # passed »), et son stop() lance PresentMon --terminate_existing_session, qui
    # couperait la session de l'appli installée sur le PC de test.
    mp = pytest.MonkeyPatch()
    mp.setattr(cachymonitor.Sampler, "start", lambda self: None)
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
