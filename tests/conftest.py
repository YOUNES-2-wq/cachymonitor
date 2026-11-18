import os
import sys

# Les tests tournent sans ecran : Qt n'est de toute facon pas necessaire ici.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import pytest  # noqa: E402

from cachymon import debug, pawnio  # noqa: E402


@pytest.fixture(autouse=True)
def journal_isole(tmp_path, monkeypatch):
    # Aucun test n'écrit dans le vrai journal de l'utilisateur
    # (%LOCALAPPDATA%\CachyMonitor\debug.log) : un test qui simule --debug
    # laissait le mode débogage actif (cache de enabled()) pour les suivants.
    # Chaque test repart d'un état neuf ; ceux qui en ont besoin le changent.
    monkeypatch.setattr(debug, "_enabled", False)
    monkeypatch.setattr(debug, "_seen", set())
    monkeypatch.setattr(debug, "_started", [])
    chemin = str(tmp_path / "debug.log")
    monkeypatch.setattr(debug, "_log_path_once", lambda: chemin)


@pytest.fixture(autouse=True)
def caches_vides():
    # Résultats mis en cache pour la session de l'appli : chaque test repart à neuf.
    pawnio.cpu_is_ryzen.cache_clear()
    pawnio.elevation_blocker.cache_clear()
    pawnio.token_elevation_type.cache_clear()
    # « Environnement durci » : propre au process, jamais hérité d'un autre test.
    pawnio.reset_env_hardened()
