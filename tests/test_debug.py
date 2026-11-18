"""Le journal de debogage ne fait rien sans --debug, et note chaque cause une fois."""
import pytest

from cachymon import debug


@pytest.fixture(autouse=True)
def chemin_recalcule(monkeypatch):
    # Le chemin du journal est mis en cache a la premiere ecriture : chaque test
    # repart d'un cache vide pour que son log_path() de test soit pris en compte.
    monkeypatch.setattr(debug, "_log_path_once", lambda: debug.log_path())


def test_silencieux_par_defaut(tmp_path, monkeypatch):
    monkeypatch.setattr(debug, "_enabled", False)
    monkeypatch.setattr(debug, "log_path", lambda: str(tmp_path / "d.log"))
    try:
        1 / 0
    except ZeroDivisionError:
        debug.debug_exc("test")
    assert not (tmp_path / "d.log").exists()


def test_note_une_seule_fois(tmp_path, monkeypatch):
    monkeypatch.setattr(debug, "_enabled", True)
    monkeypatch.setattr(debug, "_seen", set())
    monkeypatch.setattr(debug, "log_path", lambda: str(tmp_path / "d.log"))
    for _ in range(3):
        try:
            1 / 0
        except ZeroDivisionError:
            debug.debug_exc("division")
    texte = (tmp_path / "d.log").read_text()
    assert texte.count("ZeroDivisionError") == 1 and "division" in texte


def test_journal_repart_a_neuf_puis_complete(tmp_path, monkeypatch):
    log = tmp_path / "d.log"
    log.write_text("ancien lancement\n")
    monkeypatch.setattr(debug, "_enabled", True)
    monkeypatch.setattr(debug, "_seen", set())
    monkeypatch.setattr(debug, "_started", [])
    monkeypatch.setattr(debug, "log_path", lambda: str(log))
    for ctx in ("a", "b"):
        try:
            1 / 0
        except ZeroDivisionError:
            debug.debug_exc(ctx)
    texte = log.read_text()
    assert "ancien" not in texte and "a\n" in texte and "b\n" in texte
