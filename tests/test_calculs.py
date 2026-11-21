"""Tests des calculs purs : ils ne demandent ni materiel ni ecran.

Ce sont eux qui protegent le plus contre une regression discrete (une jauge qui
ment, un 1% low faux) quand on retouche le code sans le materiel d'origine.
"""
import pytest

from cachymon.config import plausible_fps, plausible_temp, _as_bool
from cachymon.controllers import _sony_battery, _clean_controller_name
from cachymon.game import _percentile, game_stats, bottleneck
from cachymon.theme import temp_role
from cachymon.widgets import battery_role


# -- bornes de plausibilite ------------------------------------------------ #
@pytest.mark.parametrize("fps,attendu", [
    (60.0, 60.0), (0.0, None), (1.0, None), (1000.0, None), (2000.0, None), (None, None),
])
def test_plausible_fps(fps, attendu):
    assert plausible_fps(fps) == attendu


@pytest.mark.parametrize("t,attendu", [
    (45.0, 45.0), (0.0, None), (150.0, None), (3.4e38, None), (None, None),
])
def test_plausible_temp(t, attendu):
    assert plausible_temp(t) == attendu


@pytest.mark.parametrize("valeur,attendu", [
    (True, True), (False, False), ("true", True), ("false", False),
    ("1", True), ("0", False), (None, False),
])
def test_as_bool(valeur, attendu):
    assert _as_bool(valeur) == attendu


# -- percentiles et statistiques de jeu ------------------------------------ #
def test_percentile_vide_et_bornes():
    assert _percentile([], 0.5) is None
    vals = [10.0, 20.0, 30.0, 40.0]
    assert _percentile(vals, 0.0) == 10.0
    assert _percentile(vals, 1.0) == 40.0


def _session(fps_list, pas=0.1, debut=10.0):
    return [(debut + i * pas, f, 1000.0 / f) for i, f in enumerate(fps_list)]


def test_game_stats_vide():
    assert game_stats([], True, "x") is None


def test_game_stats_valeurs_simples():
    st = game_stats(_session([100.0] * 50), True, "Jeu")
    assert st["avg"] == pytest.approx(100.0)
    assert st["min"] == st["max"] == 100.0
    assert st["fps"] == 100.0 and st["name"] == "Jeu"
    assert st["samples"] == 50


def test_game_stats_low_voit_les_saccades():
    fps = [100.0] * 98 + [20.0, 20.0]
    st = game_stats(_session(fps), True, "Jeu")
    assert st["low1"] < 50          # le 1% low doit refleter les chutes
    assert st["avg"] > 90           # la moyenne, peu


def test_game_stats_hors_ligne_masque_le_fps_courant():
    st = game_stats(_session([60.0] * 10), False, "Jeu")
    assert st["fps"] is None and st["frametime"] is None


def test_game_stats_fenetre_glissante():
    # Un trou de chargement tres ancien (hors fenetre de 60 s) ne doit plus peser.
    ancien = [(0.0 + i * 0.1, 5.0, 200.0) for i in range(20)]
    recent = [(200.0 + i * 0.1, 100.0, 10.0) for i in range(100)]
    st = game_stats(ancien + recent, True, "Jeu")
    assert st["low01"] == pytest.approx(100.0)
    assert st["min"] == 5.0         # mais le minimum de session, lui, le garde


def test_game_stats_extra():
    st = game_stats(_session([60.0] * 5), True, "Jeu", extra={"source": "X"})
    assert st["source"] == "X"


# -- goulot d'etranglement ------------------------------------------------- #
def test_bottleneck_inconnu():
    assert bottleneck(None, 50) == (None, None)
    assert bottleneck(50, None) == (None, None)


@pytest.mark.parametrize("cpu,gpu,role", [
    (40, 99, "gpu"), (90, 60, "cpu"), (30, 30, "muted"), (82, 88, "muted"),
])
def test_bottleneck_roles(cpu, gpu, role):
    assert bottleneck(cpu, gpu)[1] == role


# -- couleurs -------------------------------------------------------------- #
@pytest.mark.parametrize("t,role", [
    (None, "muted"), (40, "ok"), (69.9, "ok"), (70, "warn"), (84.9, "warn"), (85, "bad"),
])
def test_temp_role(t, role):
    assert temp_role(t) == role


@pytest.mark.parametrize("pct,role", [
    (None, "muted"), (100, "ok"), (51, "ok"), (50, "warn"), (21, "warn"), (20, "bad"), (0, "bad"),
])
def test_battery_role(pct, role):
    assert battery_role(pct) == role


# -- batterie des manettes Sony -------------------------------------------- #
def test_sony_dualsense():
    assert _sony_battery("dualsense", 0x09) == (95, "discharging")
    assert _sony_battery("dualsense", 0x19) == (95, "charging")
    assert _sony_battery("dualsense", 0x20) == (100, "full")
    assert _sony_battery("dualsense", 0x30) == (None, None)     # defaut signale


def test_sony_dualshock4():
    assert _sony_battery("dualshock4", 0x04) == (45, "discharging")
    assert _sony_battery("dualshock4", 0x14) == (45, "charging")
    assert _sony_battery("dualshock4", 0x1B) == (100, "full")
    assert _sony_battery("dualshock4", 0x1E) == (None, None)    # defaut de charge


def test_nom_de_manette_sans_prefixe_constructeur():
    assert _clean_controller_name("Sony Interactive Entertainment DualSense Wireless Controller") \
        == "DualSense Wireless Controller"
