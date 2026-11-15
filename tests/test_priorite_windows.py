"""Ordre des sources de FPS sous Windows (1.6.0) : PresentMon d'abord, RivaTuner en secours.

Le lecteur est construit sans __init__ (qui lancerait PresentMon) et ses deux
sources sont remplacees par des faux qui renvoient une session toute faite.
"""
from cachymon.game_windows import WindowsGameReader


class _Faux:
    def __init__(self, session):
        self.session = session

    def sample(self):
        return None if self.session is None else dict(self.session)


def _lecteur(pm, rtss):
    r = WindowsGameReader.__new__(WindowsGameReader)
    r._pm = None if pm is False else _Faux(pm)
    r._rtss = _Faux(rtss)
    return r


PM_DIRECT = {"live": True, "source": "PresentMon"}
PM_FINI = {"live": False, "source": "PresentMon"}
RT_DIRECT = {"live": True}
RT_FINI = {"live": False}


def test_presentmon_prioritaire_quand_les_deux_mesurent():
    assert _lecteur(PM_DIRECT, RT_DIRECT).sample()["source"] == "PresentMon"


def test_rivatuner_en_secours_si_presentmon_ne_mesure_rien():
    assert _lecteur(None, RT_DIRECT).sample()["source"] == "RivaTuner"
    assert _lecteur(PM_FINI, RT_DIRECT).sample()["source"] == "RivaTuner"


def test_rivatuner_seul_si_presentmon_absent():
    assert _lecteur(False, RT_DIRECT).sample()["source"] == "RivaTuner"


def test_session_terminee_presentmon_en_priorite():
    assert _lecteur(PM_FINI, RT_FINI).sample()["source"] == "PresentMon"
    assert _lecteur(None, RT_FINI).sample()["source"] == "RivaTuner"


def test_rien_du_tout():
    assert _lecteur(None, None).sample() is None
    assert _lecteur(False, None).sample() is None
