"""Calculs du lecteur PawnIO (1.7.0) et garde-fous de la relance en administrateur."""

import sys

import pytest

from cachymon import elevation, pawnio, winapi
from cachymon.pawnio import decode_tctl, energy_watts


def test_tctl_simple():
    # 35,5 °C : 284 huitièmes de degré dans les bits 21 à 31.
    assert decode_tctl(284 << 21) == 35.5


def test_tctl_plage_moins_49():
    # Bit de plage : la valeur lue est décalée de 49 °C.
    assert decode_tctl((84 * 8 << 21) | pawnio.TEMP_RANGE_SEL) == 35.0


def test_tctl_plage_moins_49_par_tj_sel():
    # Second signalement de la plage -49 °C (k10temp) : les deux bits TJ_SEL à 1.
    assert decode_tctl((90 * 8 << 21) | pawnio.TEMP_TJ_SEL) == 41.0
    # Un seul des deux bits ne suffit pas.
    assert decode_tctl((41 * 8 << 21) | 0x10000) == 41.0


def test_tctl_decalage_modele():
    # Un 1800X ajoute 20 °C à Tctl : on l'ôte.
    assert decode_tctl(60 * 8 << 21, offset=20.0) == 40.0


def test_energie_watts():
    unit = 1 / 65536            # unité réelle du Ryzen 5 5600 (15,26 µJ)
    assert abs(energy_watts(0, 36 * 65536, unit, 1.0) - 36.0) < 1e-9


def test_energie_debordement_32_bits():
    unit = 1 / 65536
    e0 = 0xFFFFFFFF - 10 * 65536 + 1
    assert abs(energy_watts(e0, 26 * 65536, unit, 1.0) - 36.0) < 1e-9


def test_energie_duree_nulle():
    assert energy_watts(0, 10, 1.0, 0) is None


def test_module_modifie_refuse():
    assert not pawnio.module_ok(b"pas le bon module")


# --- relance en administrateur --------------------------------------------- #

@pytest.fixture
def relance_possible(monkeypatch):
    """Toutes les conditions de la relance réunies ; chaque test en retire une."""
    monkeypatch.setattr(sys, "argv", ["cachymonitor.py"])
    monkeypatch.delenv("CACHYMONITOR_NO_ELEVATE", raising=False)
    monkeypatch.setattr(pawnio, "setting_enabled", lambda: True)
    monkeypatch.setattr(elevation, "_previous_relaunch_failed", lambda: False)
    monkeypatch.setattr(pawnio, "elevation_blocker", lambda: None)
    monkeypatch.setattr(pawnio, "is_admin", lambda: False)
    assert elevation.should_elevate()
    return monkeypatch


def test_pas_de_seconde_relance(relance_possible):
    # Jamais de boucle d'invites UAC : la copie relancée porte --elevated.
    relance_possible.setattr(sys, "argv", ["cachymonitor.py", elevation.ELEVATED_FLAG])
    assert not elevation.should_elevate()


def test_case_decochee_jamais_d_uac(relance_possible):
    # Réglage par défaut : même avec PawnIO installé (FanControl...), pas d'invite.
    relance_possible.setattr(pawnio, "setting_enabled", lambda: False)
    assert not elevation.should_elevate()


def test_variable_d_environnement(relance_possible):
    relance_possible.setenv("CACHYMONITOR_NO_ELEVATE", "1")
    assert not elevation.should_elevate()


def test_compte_standard_jamais_relance(relance_possible):
    # Compte standard : l'UAC demanderait un autre compte. On ne relance pas.
    relance_possible.setattr(pawnio, "elevation_blocker",
                             lambda: "Your Windows account is not an administrator.")
    assert not elevation.should_elevate()


def test_deja_administrateur(relance_possible):
    relance_possible.setattr(pawnio, "is_admin", lambda: True)
    assert not elevation.should_elevate()


def test_commande_de_relance(monkeypatch):
    # Toujours l'exécutable installé, avec --debug et le garde-fou, rien d'autre.
    from cachymon import debug
    monkeypatch.setattr(debug, "_enabled", None)        # recalculé depuis argv
    monkeypatch.setattr(sys, "argv", ["CachyMonitor.exe", "--debug"])
    exe, args = elevation.relaunch_command()
    assert exe == sys.executable
    assert args == ["--debug", "--elevated"]


def test_arguments_qt_jamais_transmis(monkeypatch):
    # Un programme qui lance CachyMonitor avec des options de Qt (chemins de
    # plugins) ne doit pas les faire passer dans la copie administrateur.
    from cachymon import debug
    monkeypatch.setattr(debug, "_enabled", False)
    piege = ["CachyMonitor.exe", "-platformpluginpath", r"C:\Users\x\evil", "-plugin", "x"]
    monkeypatch.setattr(sys, "argv", piege)
    _exe, args = elevation.relaunch_command()
    assert args == ["--elevated"]
    # Process durci : QApplication ne reçoit que le nom du programme.
    pawnio.mark_env_hardened()
    assert elevation.qt_arguments() == ["CachyMonitor.exe"]
    pawnio.reset_env_hardened()
    assert elevation.qt_arguments() == piege            # sans droits : inchangé


def test_debogage_transmis_a_la_copie_elevee(monkeypatch):
    # CACHYMONITOR_DEBUG ne passe pas l'UAC : il devient l'option --debug.
    from cachymon import debug
    monkeypatch.setattr(sys, "argv", ["CachyMonitor.exe"])
    monkeypatch.setattr(debug, "_enabled", True)
    _exe, args = elevation.relaunch_command()
    assert args == ["--debug", "--elevated"]


def test_dossier_protege(monkeypatch):
    monkeypatch.setattr(pawnio, "program_files", lambda: r"C:\Program Files")
    # Les variables d'environnement, modifiables sans droits, ne comptent pas.
    monkeypatch.setenv("ProgramW6432", r"C:\Users\x\AppData\Local\Programs")
    monkeypatch.setenv("ProgramFiles", r"C:\Users\x\AppData\Local\Programs")
    assert pawnio.protected_folder(r"C:\Program Files\CachyMonitor\CachyMonitor.exe")
    # Un dossier dont le nom commence pareil n'est pas Program Files.
    assert not pawnio.protected_folder(r"C:\Program Files Evil\CachyMonitor.exe")
    assert not pawnio.protected_folder(
        r"C:\Users\x\AppData\Local\Programs\CachyMonitor\CachyMonitor.exe")


@pytest.fixture
def pawnio_pret(monkeypatch, tmp_path):
    """PawnIO installé, Ryzen, bon module : seules les conditions de lancement varient."""
    module = tmp_path / pawnio.MODULE_AMD
    module.write_bytes(b"module")
    monkeypatch.setattr(pawnio, "installed", lambda: True)
    monkeypatch.setattr(pawnio, "ryzen_cpu", lambda: True)
    monkeypatch.setattr(pawnio, "_module_path", lambda: str(module))
    monkeypatch.setattr(pawnio, "module_ok", lambda blob: True)
    monkeypatch.setattr(pawnio, "is_admin", lambda: False)
    pawnio.elevation_blocker.cache_clear()
    yield monkeypatch
    pawnio.elevation_blocker.cache_clear()


def test_jamais_de_relance_depuis_les_sources(pawnio_pret):
    # Les .py sont modifiables sans droits : pas d'UAC automatique.
    pawnio_pret.delattr(sys, "frozen", raising=False)
    assert "administrator terminal" in pawnio.elevation_blocker()


def test_compte_standard_signale(pawnio_pret):
    pawnio_pret.setattr(sys, "frozen", True, raising=False)
    pawnio_pret.setattr(pawnio, "protected_folder", lambda path: True)
    pawnio_pret.setattr(pawnio, "installed_here", lambda exe: True)
    pawnio_pret.setattr(pawnio, "token_elevation_type", lambda: 1)
    assert pawnio.elevation_blocker() == "Your Windows account is not an administrator."
    pawnio.elevation_blocker.cache_clear()
    pawnio_pret.setattr(pawnio, "token_elevation_type", lambda: pawnio.TOKEN_LIMITED)
    assert pawnio.elevation_blocker() is None




def test_sans_program_files_rien_n_est_protege(monkeypatch):
    monkeypatch.setattr(pawnio, "program_files", lambda: "")
    assert not pawnio.protected_folder(r"C:\Program Files\CachyMonitor\CachyMonitor.exe")


def test_decalage_tctl_par_nom_complet(monkeypatch):
    # Règle de k10temp : nom complet ; un « PRO 2700X » n'a pas de décalage.
    for name, expected in (("AMD Ryzen 7 2700X Eight-Core Processor", 10.0),
                           ("AMD Ryzen 7 PRO 2700X Eight-Core Processor", 0.0),
                           ("AMD Ryzen Threadripper 1950X 16-Core Processor", 27.0),
                           ("AMD Ryzen 5 5600 6-Core Processor", 0.0)):
        monkeypatch.setattr(pawnio, "cpu_registry", lambda value, n=name: n)
        assert pawnio._tctl_offset() == expected, name


def test_environnement_administrateur(monkeypatch):
    # En administrateur, aucune variable posée par l'utilisateur ne doit désigner
    # un programme, une DLL ou un dossier.
    import os
    monkeypatch.setattr(pawnio, "is_admin", lambda: True)
    monkeypatch.setattr(sys, "argv", ["CachyMonitor.exe", elevation.ELEVATED_FLAG])
    # Copie de l'environnement : harden_environment() le vide entièrement, et
    # le vrai doit rester intact pour les autres tests.
    env = dict(os.environ, CACHYMONITOR_PRESENTMON=r"C:\Users\x\evil.exe",
               SystemRoot=r"C:\Users\x\fake", PATH=r"C:\Users\x\bin",
               LOCALAPPDATA=r"C:\Windows\System32")
    monkeypatch.setattr(os, "environ", env)
    dossiers = []
    monkeypatch.setattr(os, "chdir", dossiers.append)   # ne pas changer celui des tests
    elevation.harden_environment()
    assert "CACHYMONITOR_PRESENTMON" not in os.environ
    assert "LOCALAPPDATA" not in os.environ
    assert not os.environ["SystemRoot"].lower().startswith(r"c:\users")
    assert r"c:\users" not in os.environ["PATH"].lower()
    assert r"c:\users" not in os.environ["TEMP"].lower()
    # Dossier courant protégé : un programme lancé par son nom n'y est pas piégé.
    assert dossiers and dossiers[0].lower().endswith("system32")


def test_admin_sans_la_case_garde_son_environnement(monkeypatch):
    # Lancé en admin par l'utilisateur lui-même (UAC désactivé...) sans --elevated :
    # comportement de la 1.6.0, rien n'est touché.
    import os
    monkeypatch.setattr(pawnio, "is_admin", lambda: True)
    monkeypatch.setattr(pawnio, "setting_in_registry", lambda: False)
    monkeypatch.setattr(sys, "argv", ["CachyMonitor.exe"])
    env = {"PATH": r"C:\Tools", "LOCALAPPDATA": r"C:\Users\x\AppData\Local"}
    monkeypatch.setattr(os, "environ", dict(env))
    monkeypatch.setattr(os, "chdir", lambda path: pytest.fail("chdir inattendu"))
    elevation.harden_environment()
    assert os.environ == env






def test_echec_definitif_jamais_reessaye(monkeypatch):
    cpu = pawnio.PawnIoCpu()
    essais = []
    monkeypatch.setattr(cpu, "_open", lambda: essais.append(1) or False)
    assert not cpu._ready() and not cpu._ready()
    assert len(essais) == 1


class FakeSettings(dict):
    def value(self, key, default=None):
        return self.get(key, default)

    def setValue(self, key, value):
        self[key] = value

    def sync(self):
        pass


def test_pas_de_boucle_si_la_copie_elevee_plante(monkeypatch):
    # Les copies élevées n'ont jamais affiché leur fenêtre : au lancement suivant,
    # pas de nouvelle UAC, la case est décochée et un message est prévu.
    key, setting = elevation.PENDING_KEY, pawnio.SETTING_KEY
    s = FakeSettings({key: elevation.MAX_PENDING, setting: True})
    monkeypatch.setattr(elevation, "app_settings", lambda: s)
    monkeypatch.setattr(elevation, "RELAUNCH_FAILED", [])
    assert elevation._previous_relaunch_failed()
    assert s[setting] is False and s[key] == 0
    assert elevation.RELAUNCH_FAILED
    # Copie élevée arrivée à sa fenêtre : rien à signaler la fois suivante.
    s[key] = 1
    monkeypatch.setattr(sys, "argv", ["CachyMonitor.exe", elevation.ELEVATED_FLAG])
    # --elevated sans droits (raccourci tapé à la main) : ne remet pas le compteur à 0.
    monkeypatch.setattr(pawnio, "is_admin", lambda: False)
    elevation.confirm_elevated_start()
    assert s[key] == 1
    monkeypatch.setattr(pawnio, "is_admin", lambda: True)
    elevation.confirm_elevated_start()
    assert s[key] == 0 and not elevation._previous_relaunch_failed()


def test_double_clic_pendant_l_uac_n_est_pas_un_plantage(monkeypatch):
    # Une seule relance en attente (la première invite UAC est encore ouverte) :
    # un second lancement ne prend pas ça pour un plantage.
    s = FakeSettings({elevation.PENDING_KEY: 1, pawnio.SETTING_KEY: True})
    monkeypatch.setattr(elevation, "app_settings", lambda: s)
    monkeypatch.setattr(elevation, "RELAUNCH_FAILED", [])
    assert not elevation._previous_relaunch_failed()
    assert s[pawnio.SETTING_KEY] is True and not elevation.RELAUNCH_FAILED




def test_conso_ignoree_apres_une_longue_pause(monkeypatch):
    # Après une veille, la moyenne d'énergie serait fausse : relevé écarté.
    cpu = pawnio.PawnIoCpu()
    cpu._state, cpu._unit = True, 1 / 65536
    monkeypatch.setattr(cpu, "_call", lambda name, arg: 36 * 65536)
    monkeypatch.setattr(pawnio.time, "perf_counter", lambda: 1000.0)
    cpu._energy = (0, 1000.0 - pawnio.MAX_ENERGY_GAP_S - 1)
    assert cpu.power() is None


def test_pawnio_ferme_sans_la_case(monkeypatch):
    # Admin sans avoir coché la case : le pilote n'est jamais ouvert (1.6.0).
    monkeypatch.setattr(pawnio, "is_admin", lambda: True)
    monkeypatch.setattr(pawnio, "setting_enabled", lambda: False)
    monkeypatch.setattr(pawnio, "pawnio_dll", lambda: pytest.fail("pilote ouvert"))
    assert pawnio.PawnIoCpu()._open() is False




def test_famille_du_processeur():
    assert pawnio.cpu_family("AMD64 Family 25 Model 33 Stepping 2") == 25     # Zen 3
    assert pawnio.cpu_family("AMD64 Family 21 Model 2 Stepping 0") == 21      # FX
    assert pawnio.cpu_family("") is None


def test_amd_fx_refuse(monkeypatch):
    # Le module AMDFamily17 n'accepte que les familles 17h à 1Ah (Ryzen).
    values = {"VendorIdentifier": "AuthenticAMD", "Identifier": "AMD64 Family 21 Model 2"}
    monkeypatch.setattr(pawnio, "cpu_registry", lambda v: values[v])
    assert not pawnio.ryzen_cpu()
    values["Identifier"] = "AMD64 Family 25 Model 33 Stepping 2"
    pawnio.cpu_is_ryzen.cache_clear()      # en cache pour la session
    assert pawnio.ryzen_cpu()


def test_environnement_sur_liste_blanche():
    # Toute variable non prévue disparaît, dont celles de Qt.
    old = {"QT_PLUGIN_PATH": r"C:\Temp\evil", "QT_QPA_PLATFORM_PLUGIN_PATH": "x",
           "PATH": r"C:\Users\x\bin", "CACHYMONITOR_PRESENTMON": "evil.exe",
           "LANG": "fr_FR.UTF-8", "CACHYMONITOR_DEBUG": "1", "_PYI_APPLICATION_HOME_DIR": "d"}
    env = elevation.safe_environment(old, r"C:\Windows", r"C:\Windows\System32",
                                     r"C:\Users\x", r"C:\Program Files")
    for var in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "CACHYMONITOR_PRESENTMON"):
        assert var not in env
    assert env["LANG"] == "fr_FR.UTF-8" and env["CACHYMONITOR_DEBUG"] == "1"
    assert "_PYI_APPLICATION_HOME_DIR" not in env
    assert "Users" not in env["PATH"] and env["SystemRoot"] == r"C:\Windows"
    assert env["USERPROFILE"] == r"C:\Users\x" and "LOCALAPPDATA" not in env
    assert env["TEMP"].startswith(r"C:\Windows")


def test_environnement_sans_dossier_windows():
    # Si Windows ne répond pas : valeur fixe par défaut, jamais celle héritée.
    env = elevation.safe_environment({"SystemRoot": r"C:\Users\x\fake"}, None, None, None, "")
    assert env["SystemRoot"] == elevation.DEFAULT_WINDIR
    assert "Users" not in env["PATH"]


def test_environnement_qt_de_l_appli():
    # Les réglages Qt posés par PyInstaller sont refaits depuis le dossier de
    # l'appli, pas repris de l'utilisateur.
    bundle = r"C:\Program Files\CachyMonitor\_internal"
    env = elevation.safe_environment({"QT_PLUGIN_PATH": r"C:\Temp\evil"}, r"C:\Windows",
                                     r"C:\Windows\System32", None, "", bundle)
    assert env["QT_PLUGIN_PATH"].startswith(bundle)
    import os
    assert env["PATH"].split(os.pathsep)[0] == bundle






class _FauxKernel32:
    """OpenMutexW / CreateMutexW simulés : handle rendu et erreur Windows."""
    def __init__(self, handle, erreur):
        self.handle, self.erreur, self.fermes = handle, erreur, []

    def _appel(self, *args):
        import ctypes
        ctypes.set_last_error(self.erreur)
        return self.handle

    OpenMutexW = CreateMutexW = _appel

    def CloseHandle(self, handle):
        self.fermes.append(handle)


@pytest.mark.parametrize("handle, erreur, existe", [
    (7, 0, True),       # ouvert : il existe
    (None, 5, True),    # accès refusé : celui d'une copie admin, il existe
    (None, 2, False),   # introuvable
    (None, 6, False),   # autre erreur (nom pris par autre chose) : absent
])
def test_verrou_existant(monkeypatch, handle, erreur, existe):
    k32 = _FauxKernel32(handle, erreur)
    monkeypatch.setattr(winapi, "kernel32_api", lambda: k32)
    assert elevation._mutex_exists("x") is existe










@pytest.fixture
def ouverture_demandee(monkeypatch):
    monkeypatch.setattr(pawnio, "is_admin", lambda: True)
    monkeypatch.setattr(pawnio, "env_hardened", lambda: True)
    monkeypatch.setattr(pawnio, "cpu_is_ryzen", lambda: True)
    monkeypatch.setattr(pawnio, "setting_enabled", lambda: True)
    monkeypatch.setattr(pawnio, "ryzen_cpu", lambda: True)
    return monkeypatch


def test_pilote_introuvable_est_definitif(ouverture_demandee):
    ouverture_demandee.setattr(pawnio, "pawnio_dll", lambda: None)
    cpu = pawnio.PawnIoCpu()
    assert cpu.temp() is None and cpu.failure_reason() == cpu.MISSING_DRIVER


def test_module_absent_est_definitif(ouverture_demandee):
    ouverture_demandee.setattr(pawnio, "pawnio_dll", lambda: r"C:\x\PawnIOLib.dll")
    ouverture_demandee.setattr(pawnio, "_module_path", lambda: None)
    cpu = pawnio.PawnIoCpu()
    assert cpu.temp() is None and cpu.failure_reason() == cpu.BAD_MODULE






def test_type_de_jeton_inconnu_pas_garde(monkeypatch):
    # Un échec passager (0) n'est pas gardé pour toute la session.
    pawnio.token_elevation_type.cache_clear()
    valeurs = [None, pawnio.TOKEN_LIMITED]
    monkeypatch.setattr(pawnio, "_read_token_type", lambda: valeurs.pop(0))
    assert pawnio.token_elevation_type() is None
    assert pawnio.token_elevation_type() == pawnio.TOKEN_LIMITED
    assert pawnio.token_elevation_type() == pawnio.TOKEN_LIMITED     # gardé


def test_dossier_temporaire_inscriptible(tmp_path):
    assert elevation._writable_dir(str(tmp_path))
    assert not list(tmp_path.iterdir())                 # fichier d'essai effacé
    assert not elevation._writable_dir(str(tmp_path / "absent"))


def test_journal_une_seule_premiere_ecriture(tmp_path, monkeypatch):
    # Deux threads qui écrivent en même temps : aucune entrée perdue.
    import threading
    from cachymon import debug
    monkeypatch.setattr(debug, "_enabled", True)
    chemin = str(tmp_path / "d.log")
    monkeypatch.setattr(debug, "_log_path_once", lambda: chemin)
    fils = [threading.Thread(target=debug.debug_msg, args=("ctx%d" % i, "texte"))
            for i in range(8)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    texte = (tmp_path / "d.log").read_text(encoding="utf-8")
    assert all("ctx%d" % i in texte for i in range(8))








def test_dll_trop_ancienne_est_definitive(ouverture_demandee, tmp_path):
    # Fonction manquante dans PawnIOLib.dll (vieille version) : pas d'essais en boucle.
    module = tmp_path / "m.bin"
    module.write_bytes(b"x")
    ouverture_demandee.setattr(pawnio, "pawnio_dll", lambda: r"C:\x\PawnIOLib.dll")
    ouverture_demandee.setattr(pawnio, "_module_path", lambda: str(module))
    ouverture_demandee.setattr(pawnio, "module_ok", lambda blob: True)

    class VieilleDll:
        pass
    ouverture_demandee.setattr(pawnio.ctypes, "WinDLL", lambda *a, **k: VieilleDll())
    cpu = pawnio.PawnIoCpu()
    assert cpu.temp() is None and cpu.failure_reason() == cpu.DRIVER_REFUSED



def test_admin_avec_la_case_environnement_durci(monkeypatch):
    # Lancé en admin par l'utilisateur, case cochée : PawnIO sera ouvert, donc
    # même protection que la copie relancée.
    monkeypatch.setattr(pawnio, "is_admin", lambda: True)
    monkeypatch.setattr(sys, "argv", ["CachyMonitor.exe"])
    monkeypatch.setattr(pawnio, "setting_in_registry", lambda: True)
    assert elevation.will_open_pawnio()
    monkeypatch.setattr(pawnio, "setting_in_registry", lambda: False)
    assert not elevation.will_open_pawnio()
    monkeypatch.setattr(pawnio, "is_admin", lambda: False)
    monkeypatch.setattr(pawnio, "setting_in_registry", lambda: True)
    assert not elevation.will_open_pawnio()





def test_pas_d_ouverture_sans_environnement_durci(ouverture_demandee):
    # Admin et case cochée, mais environnement pas durci au démarrage : le
    # pilote n'est pas ouvert (rien à signaler non plus).
    ouverture_demandee.setattr(pawnio, "env_hardened", lambda: False)
    ouverture_demandee.setattr(pawnio, "pawnio_dll", lambda: pytest.fail("pilote ouvert"))
    cpu = pawnio.PawnIoCpu()
    assert cpu.temp() is None and cpu.failure_reason() is None









def test_jeton_illisible_raison_neutre(monkeypatch):
    # Jeton illisible : on ne prétend pas que le compte n'est pas administrateur.
    monkeypatch.setattr(pawnio, "ryzen_cpu", lambda: True)
    monkeypatch.setattr(pawnio, "installed", lambda: True)
    monkeypatch.setattr(pawnio, "_module_path", lambda: __file__)
    monkeypatch.setattr(pawnio, "module_ok", lambda blob: True)
    monkeypatch.setattr(pawnio, "is_admin", lambda: False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(pawnio, "protected_folder", lambda path: True)
    monkeypatch.setattr(pawnio, "installed_here", lambda exe: True)
    monkeypatch.setattr(pawnio, "token_elevation_type", lambda: None)
    assert "Could not check" in pawnio.elevation_blocker()




def test_journal_indisponible_ne_plante_jamais(monkeypatch):
    from cachymon import debug
    monkeypatch.setattr(debug, "_enabled", True)

    def casse():
        raise OSError("registre")
    monkeypatch.setattr(debug, "_log_path_once", casse)
    assert debug.unavailable() is False



def test_processeur_illisible_pas_garde(monkeypatch):
    # Registre muet une fois : pas gardé comme « pas un Ryzen » pour la session.
    valeurs = {"VendorIdentifier": "", "Identifier": ""}
    monkeypatch.setattr(pawnio, "cpu_registry", lambda v: valeurs[v])
    assert not pawnio.ryzen_cpu()
    valeurs.update(VendorIdentifier="AuthenticAMD", Identifier="AMD64 Family 25 Model 33")
    assert pawnio.ryzen_cpu()
    valeurs["Identifier"] = "AMD64 Family 21"
    assert pawnio.ryzen_cpu()           # lu une fois : gardé


def test_is_admin_reel():
    assert pawnio.is_admin() in (True, False)



def test_admin_hors_program_files_n_ouvre_pas_pawnio(monkeypatch):
    # Admin lancé par l'utilisateur, case cochée, mais exe hors de Program Files :
    # pas de PawnIO (PresentMon et le pilote ne tournent en admin que protégés).
    monkeypatch.setattr(sys, "argv", ["CachyMonitor.exe"])
    monkeypatch.setattr(pawnio, "is_admin", lambda: True)
    monkeypatch.setattr(pawnio, "setting_in_registry", lambda: True)
    monkeypatch.setattr(pawnio, "ryzen_cpu", lambda: True)
    monkeypatch.setattr(pawnio, "installed", lambda: True)
    monkeypatch.setattr(pawnio, "_module_path", lambda: __file__)
    monkeypatch.setattr(pawnio, "module_ok", lambda blob: True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(pawnio, "protected_folder", lambda path: False)
    assert pawnio.elevation_blocker() is not None
    assert not elevation.will_open_pawnio()
    pawnio.elevation_blocker.cache_clear()
    monkeypatch.setattr(pawnio, "protected_folder", lambda path: True)
    monkeypatch.setattr(pawnio, "installed_here", lambda exe: True)
    assert elevation.will_open_pawnio()


def test_import_ne_durcit_rien(monkeypatch):
    # Importer le point d'entrée (tests) ne touche ni l'environnement ni le dossier.
    import importlib
    import os
    avant_env, avant_dossier = dict(os.environ), os.getcwd()
    import cachymonitor
    importlib.reload(cachymonitor)
    assert dict(os.environ) == avant_env and os.getcwd() == avant_dossier





def test_dossier_d_installation_exact(monkeypatch, tmp_path):
    # Sous Program Files ne suffit pas : il faut le dossier inscrit par notre
    # installateur (HKLM), pas un sous-dossier laissé modifiable par un autre logiciel.
    monkeypatch.setattr(pawnio, "protected_folder", lambda path: True)
    monkeypatch.setattr(pawnio, "hklm", lambda key, value: r"C:\Program Files\CachyMonitor" + "\\")
    assert pawnio.installed_here(r"C:\Program Files\CachyMonitor\CachyMonitor.exe")
    assert not pawnio.installed_here(r"C:\Program Files\Foo\CachyMonitor.exe")
    monkeypatch.setattr(pawnio, "hklm", lambda key, value: "")        # pas installé pour tous
    assert not pawnio.installed_here(r"C:\Program Files\CachyMonitor\CachyMonitor.exe")









def test_blocker_non_garde_si_registre_muet(monkeypatch):
    # Registre muet au démarrage : « pas un Ryzen » ne doit pas rester en cache.
    pawnio.elevation_blocker.cache_clear()
    monkeypatch.setattr(pawnio, "cpu_is_ryzen", lambda: None)
    monkeypatch.setattr(pawnio, "ryzen_cpu", lambda: False)
    assert pawnio.elevation_blocker() == "Only AMD Ryzen processors are supported."
    monkeypatch.setattr(pawnio, "cpu_is_ryzen", lambda: True)
    monkeypatch.setattr(pawnio, "ryzen_cpu", lambda: True)
    monkeypatch.setattr(pawnio, "installed", lambda: False)
    assert pawnio.elevation_blocker() == "The PawnIO driver is not installed."
    pawnio.elevation_blocker.cache_clear()






def test_program_files_muet_n_est_pas_garde(monkeypatch):
    pawnio.program_files.cache_clear()
    monkeypatch.setattr(pawnio, "hklm", lambda subkey, value: "")
    assert not pawnio.program_files()
    monkeypatch.setattr(pawnio, "hklm", lambda subkey, value: r"C:\Program Files")
    assert pawnio.program_files() == r"C:\Program Files"
    pawnio.program_files.cache_clear()


def test_blocker_jeton_illisible_n_est_pas_garde(monkeypatch):
    pawnio.elevation_blocker.cache_clear()
    monkeypatch.setattr(pawnio, "_blocker_reason",
                        lambda: "Could not check your Windows account. Open the Options again to retry.")
    monkeypatch.setattr(pawnio, "cpu_is_ryzen", lambda: True)
    monkeypatch.setattr(pawnio, "program_files", lambda: r"C:\Program Files")
    assert pawnio.elevation_blocker().startswith("Could not check")
    monkeypatch.setattr(pawnio, "_blocker_reason", lambda: None)
    assert pawnio.elevation_blocker() is None       # réessayé, pas resté en cache
    monkeypatch.setattr(pawnio, "_blocker_reason", lambda: "autre")
    assert pawnio.elevation_blocker() is None       # définitif, gardé
    pawnio.elevation_blocker.cache_clear()


def test_verrou_partage_est_ouvert_a_tous():
    # Le verrou Access_PCI créé par nous (souvent en administrateur) doit donner
    # l'accès complet à « Tout le monde » (WD), sinon les autres outils sont bloqués.
    import ctypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.GetSecurityInfo.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ulong,
                                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p]
    name = r"Local\CachyMonitor-test-partage-pytest"
    handle, existed = winapi.create_mutex(name, shared=True)
    assert handle and not existed
    try:
        descriptor, text = ctypes.c_void_p(), ctypes.c_void_p()
        assert advapi32.GetSecurityInfo(handle, 6, 4, None, None, None, None,
                                        ctypes.byref(descriptor)) == 0
        assert advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, 4, ctypes.byref(text), None)
        assert "WD" in ctypes.wstring_at(text.value)
    finally:
        winapi.kernel32_api().CloseHandle(handle)




def test_journal_inconnu_n_est_pas_garde(monkeypatch):
    # Un « pas de fichier » venu d'un registre muet ne doit pas durer toute la session.
    from cachymon import debug
    monkeypatch.undo()      # retire le journal isolé de conftest : on teste le vrai cache
    monkeypatch.setattr(debug, "_log_path_cell", [])
    valeurs = iter([None, "fichier-journal"])
    monkeypatch.setattr(debug, "log_path", lambda: next(valeurs))
    assert debug._log_path_once() is None
    assert debug._log_path_once() == "fichier-journal"
    assert debug._log_path_once() == "fichier-journal"      # gardé une fois connu




def test_presentmon_variable_ignoree_en_admin(monkeypatch, tmp_path):
    from cachymon import game_windows
    faux = tmp_path / "PresentMon.exe"
    faux.write_bytes(b"x")
    monkeypatch.setenv("CACHYMONITOR_PRESENTMON", str(faux))
    monkeypatch.setattr(pawnio, "is_admin", lambda: False)
    assert game_windows.find_presentmon() == str(faux)
    monkeypatch.setattr(pawnio, "is_admin", lambda: True)
    assert game_windows.find_presentmon() != str(faux)


def test_copie_relancee_durcie_meme_si_pawnio_refuse(monkeypatch):
    # La copie relancée tourne en administrateur : son environnement est nettoyé
    # même si, au dernier moment, PawnIO est refusé (registre illisible...). Mais
    # PawnIO, lui, ne s'ouvre pas (pas de drapeau « durci »), et Qt ne reçoit
    # aucun argument de la ligne de commande.
    import os
    monkeypatch.setattr(pawnio, "is_admin", lambda: True)
    monkeypatch.setattr(pawnio, "elevation_blocker", lambda: "The AMD module is missing")
    monkeypatch.setattr(sys, "argv", ["CachyMonitor.exe", elevation.ELEVATED_FLAG,
                                      "-platformpluginpath", r"C:\Users\x\evil"])
    monkeypatch.setattr(os, "environ", {"QT_PLUGIN_PATH": r"C:\Users\x\evil", "PATH": r"C:\Users\x"})
    monkeypatch.setattr(os, "chdir", lambda path: None)
    elevation.harden_environment()
    assert "QT_PLUGIN_PATH" not in os.environ
    assert not pawnio.env_hardened()
    assert elevation.qt_arguments() == ["CachyMonitor.exe"]



# --- code simplifié : un seul essai, un seul verrou ----------------------- #

def test_un_seul_essai_d_ouverture(ouverture_demandee):
    # Exception à l'ouverture (pilote pas prêt...) : « sans réponse » pour la
    # session, jamais de nouvel essai.
    cpu = pawnio.PawnIoCpu()
    essais = []

    def ouvrir():
        essais.append(1)
        raise OSError("pawnio_open : 0x80070015")
    ouverture_demandee.setattr(cpu, "_open", ouvrir)
    assert cpu.temp() is None and cpu.power() is None and cpu.temp() is None
    assert len(essais) == 1
    assert cpu.tried() and not cpu.active() and not cpu.owns_cpu_sensor()
    assert cpu.failure_reason() == cpu.NO_RESPONSE


def test_causes_d_echec(ouverture_demandee):
    cpu = pawnio.PawnIoCpu()
    assert cpu.failure_reason() is None and not cpu.tried()     # pas encore essayé
    cpu._state = False
    assert cpu.failure_reason() is None                         # pas demandé
    for cause in (cpu.UNSUPPORTED, cpu.BAD_MODULE, cpu.MISSING_DRIVER,
                  cpu.DRIVER_REFUSED, cpu.PCI_BUSY, cpu.NO_RESPONSE):
        cpu._failure = cause
        assert cpu.failure_reason() == cause
    cpu._state = True                                           # ouvert : aucune cause
    assert cpu.failure_reason() is None and cpu.active() and cpu.owns_cpu_sensor()
    assert set(cpu.TRANSIENT) == {cpu.PCI_BUSY, cpu.NO_RESPONSE}


def test_pas_demande_rien_a_signaler(monkeypatch):
    # Pas admin (ou case décochée, ou pas Ryzen) : aucun échec à signaler.
    monkeypatch.setattr(pawnio, "is_admin", lambda: False)
    cpu = pawnio.PawnIoCpu()
    assert cpu.temp() is None and cpu.tried() and cpu.failure_reason() is None
    assert not cpu.owns_cpu_sensor()


def test_registre_processeur_muet_pas_de_pilote(ouverture_demandee):
    # Registre muet : PawnIO n'est pas ouvert cette fois (Afterburner reprend),
    # sans message ni nouvel essai.
    ouverture_demandee.setattr(pawnio, "cpu_is_ryzen", lambda: None)
    ouverture_demandee.setattr(pawnio, "pawnio_dll", lambda: pytest.fail("pilote ouvert"))
    cpu = pawnio.PawnIoCpu()
    assert cpu.temp() is None and cpu.failure_reason() is None


def test_messages_d_echec_traduits():
    # Chaque cause durable a un message, et chaque message sa traduction française.
    import cachymonitor
    from cachymon.i18n import TRANSLATIONS
    cpu = pawnio.PawnIoCpu
    assert set(cachymonitor.PAWNIO_FAILURE_MESSAGES) == (
        {cpu.UNSUPPORTED, cpu.BAD_MODULE, cpu.MISSING_DRIVER, cpu.DRIVER_REFUSED})
    for message in (*cachymonitor.PAWNIO_FAILURE_MESSAGES.values(),
                    cachymonitor.PAWNIO_TRANSIENT_MESSAGE):
        assert message in TRANSLATIONS["fr"], message


class _FenetreFausse:
    """Ce que _check_pawnio_started lit de la fenêtre."""

    def __init__(self, coche=True):
        self._pawnio_checked = False
        self.pawnio_box = type("Case", (), {"isChecked": lambda self: coche})()
        self.coupee = []

    def _turn_pawnio_off(self, reason):
        self.coupee.append(reason)


def _verifier(monkeypatch, fenetre, *, durci=True, essaye=True, cause=None):
    import cachymonitor
    messages = []
    monkeypatch.setattr(cachymonitor, "env_hardened", lambda: durci)
    faux = type("P", (), {"TRANSIENT": pawnio.PawnIoCpu.TRANSIENT,
                          "tried": lambda self: essaye,
                          "failure_reason": lambda self: cause})()
    monkeypatch.setattr(cachymonitor, "PAWNIO", faux)
    monkeypatch.setattr(cachymonitor.QTimer, "singleShot",
                        staticmethod(lambda ms, fn: messages.append(fn)))
    cachymonitor.MainWindow._check_pawnio_started(fenetre)
    return messages


def test_fenetre_cause_durable_decoche(monkeypatch):
    f = _FenetreFausse()
    _verifier(monkeypatch, f, cause=pawnio.PawnIoCpu.UNSUPPORTED)
    assert f.coupee == [pawnio.PawnIoCpu.UNSUPPORTED] and f._pawnio_checked


def test_fenetre_cause_passagere_garde_la_case(monkeypatch):
    f = _FenetreFausse()
    messages = _verifier(monkeypatch, f, cause=pawnio.PawnIoCpu.NO_RESPONSE)
    assert f.coupee == [] and len(messages) == 1 and f._pawnio_checked


def test_fenetre_attend_la_premiere_tentative(monkeypatch):
    f = _FenetreFausse()
    _verifier(monkeypatch, f, essaye=False, cause=pawnio.PawnIoCpu.UNSUPPORTED)
    assert f.coupee == [] and not f._pawnio_checked


def test_fenetre_rien_a_dire_si_ouvert_ou_decoche_ou_non_durci(monkeypatch):
    f = _FenetreFausse()
    assert _verifier(monkeypatch, f, cause=None) == [] and f.coupee == []
    f = _FenetreFausse(coche=False)
    _verifier(monkeypatch, f, cause=pawnio.PawnIoCpu.UNSUPPORTED)
    assert f.coupee == []
    f = _FenetreFausse()
    _verifier(monkeypatch, f, durci=False, cause=pawnio.PawnIoCpu.UNSUPPORTED)
    assert f.coupee == [] and f._pawnio_checked          # plus rien à surveiller


def test_deja_une_copie_admin_donne_busy(relance_possible):
    # Un nouveau lancement qui voit le verrou de la copie élevée ne relance rien :
    # ni seconde invite UAC, ni compteur de plantages touché.
    relance_possible.setattr(elevation, "_mutex_exists", lambda name: name == elevation.ADMIN_MUTEX)
    relance_possible.setattr(elevation, "_previous_relaunch_failed",
                             lambda: pytest.fail("compteur consulté"))
    relance_possible.setattr(elevation, "_relaunch", lambda: pytest.fail("seconde invite UAC"))
    assert elevation.relaunch_elevated() == elevation.BUSY


def test_pas_de_verrou_on_relance(relance_possible):
    relance_possible.setattr(elevation, "_mutex_exists", lambda name: False)
    relance_possible.setattr(elevation, "_relaunch", lambda: True)
    assert elevation.relaunch_elevated() == elevation.STARTED
    relance_possible.setattr(elevation, "_relaunch", lambda: False)     # UAC refusée
    assert elevation.relaunch_elevated() is None


def test_case_decochee_aucune_verification(relance_possible):
    relance_possible.setattr(pawnio, "setting_enabled", lambda: False)
    relance_possible.setattr(elevation, "_mutex_exists", lambda name: pytest.fail("vérifié"))
    assert elevation.relaunch_elevated() is None


def test_seconde_copie_admin_est_signalee(monkeypatch):
    # Admin lancé alors que le verrou de la copie élevée existe déjà.
    monkeypatch.setattr(pawnio, "env_hardened", lambda: True)
    monkeypatch.setattr(elevation, "_admin_handle", [])
    monkeypatch.setattr(elevation, "DUPLICATE_ADMIN", [])
    monkeypatch.setattr(winapi, "create_mutex", lambda name, shared=False: (7, True))
    elevation.hold_admin_instance()
    assert elevation.DUPLICATE_ADMIN and elevation._admin_handle == [7]
    monkeypatch.setattr(elevation, "_admin_handle", [])
    monkeypatch.setattr(elevation, "DUPLICATE_ADMIN", [])
    monkeypatch.setattr(winapi, "create_mutex", lambda name, shared=False: (8, False))
    elevation.hold_admin_instance()
    assert not elevation.DUPLICATE_ADMIN and elevation._admin_handle == [8]


def test_journal_en_administrateur(monkeypatch):
    # En admin : jamais de fichier (le dossier de l'utilisateur ne doit pas être
    # écrit avec les droits administrateur).
    from cachymon import debug
    monkeypatch.setattr(pawnio, "is_admin", lambda: True)
    assert debug.log_path() is None
    monkeypatch.setattr(pawnio, "is_admin", lambda: False)
    assert debug.log_path() is not None


def test_appels_windows_reels():
    # Les liaisons ctypes partagées (kernel32_api, verrous nommés) marchent vraiment.
    import os
    windir, system32 = elevation._system_dirs()
    assert os.path.isdir(windir) and os.path.isdir(system32)
    nom = r"Local\CachyMonitor-test-pytest"
    assert elevation._mutex_exists(r"Local\CachyMonitor-test-inexistant") is False
    handle, existait = winapi.create_mutex(nom)
    try:
        assert handle and not existait
        assert elevation._mutex_exists(nom)
        deuxieme, existait = winapi.create_mutex(nom)
        assert existait
        winapi.kernel32_api().CloseHandle(deuxieme)
    finally:
        winapi.kernel32_api().CloseHandle(handle)
    with winapi.process_token() as token:
        assert token
