"""Mise à jour intégrée : numéros de version, lecture de la release, empreinte."""
import hashlib
import io

import pytest

from cachymon import updater

SHA = "a" * 64


def _release(**kw):
    data = {
        "tag_name": "v1.7.1", "draft": False, "prerelease": False,
        "html_url": "https://github.com/YOUNES-2-wq/cachymonitor/releases/tag/v1.7.1",
        "assets": [{
            "name": "CachyMonitor-Setup-1.7.1.exe", "size": 10,
            "browser_download_url": "https://github.com/YOUNES-2-wq/cachymonitor/releases/"
                                    "download/v1.7.1/CachyMonitor-Setup-1.7.1.exe",
            "digest": "sha256:" + SHA}],
    }
    data.update(kw)
    return data


def test_versions():
    assert updater.parse_version("v1.7.1") == (1, 7, 1)
    assert updater.parse_version("1.8.0-beta") is None
    assert updater.parse_version(None) is None
    assert updater.is_newer("1.7.1", "1.7.0")
    assert updater.is_newer("1.10.0", "1.9.9")        # numérique, pas alphabétique
    assert not updater.is_newer("1.7.0", "1.7.0")
    assert not updater.is_newer("1.7", "1.7.0")
    assert not updater.is_newer("1.6.9", "1.7.0")
    assert not updater.is_newer("n'importe quoi", "1.7.0")


def test_release_normale():
    r = updater.release_from_json(_release())
    assert r.version == "1.7.1" and r.installable and r.sha256 == SHA


@pytest.mark.parametrize("changes", [{"draft": True}, {"prerelease": True},
                                     {"tag_name": "nightly"}])
def test_release_ignoree(changes):
    assert updater.release_from_json(_release(**changes)) is None


def test_sans_empreinte_ou_hors_github_pas_installable():
    sans = _release()
    sans["assets"][0]["digest"] = None
    assert not updater.release_from_json(sans).installable
    ailleurs = _release()
    ailleurs["assets"][0]["browser_download_url"] = "https://evil.example/CachyMonitor-Setup-1.7.1.exe"
    assert not updater.release_from_json(ailleurs).installable
    http = _release()
    http["assets"][0]["browser_download_url"] = "http://github.com/x/CachyMonitor-Setup-1.7.1.exe"
    assert not updater.release_from_json(http).installable


def test_mauvais_nom_de_fichier_refuse():
    r = _release()
    r["assets"][0]["name"] = "CachyMonitor-Setup-1.7.1.exe.zip"
    assert not updater.release_from_json(r).installable


class _Reponse(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _telecharge(monkeypatch, contenu):
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _Reponse(contenu))
    release = updater.release_from_json(_release())
    return updater.Release(release.version, release.page_url, release.asset_url,
                           hashlib.sha256(contenu).hexdigest() if contenu else SHA)


def test_telechargement_verifie_l_empreinte(monkeypatch):
    release = _telecharge(monkeypatch, b"contenu de l'installateur")
    path = updater.download(release)
    try:
        assert open(path, "rb").read() == b"contenu de l'installateur"
    finally:
        import shutil
        import os
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


def test_empreinte_differente_efface_le_fichier(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.tempfile, "mkdtemp", lambda prefix: str(tmp_path / "up"))
    (tmp_path / "up").mkdir()
    release = _telecharge(monkeypatch, b"x")
    release = updater.Release(release.version, release.page_url, release.asset_url, SHA)
    with pytest.raises(updater.UpdateError):
        updater.download(release)
    assert not (tmp_path / "up").exists()


def test_sans_empreinte_aucun_telechargement():
    with pytest.raises(updater.UpdateError):
        updater.download(updater.Release("1.7.1", "u", "https://github.com/x", ""))


def test_annulation_efface_le_fichier(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.tempfile, "mkdtemp", lambda prefix: str(tmp_path / "up"))
    (tmp_path / "up").mkdir()
    release = _telecharge(monkeypatch, b"x")
    with pytest.raises(updater.UpdateCancelled):
        updater.download(release, cancelled=lambda: True)
    assert not (tmp_path / "up").exists()


def test_purge_ne_touche_que_les_vieux_dossiers_de_mise_a_jour(monkeypatch, tmp_path):
    import os
    import time
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    vieux, recent, autre = (tmp_path / n for n in
                            ("CachyMonitor-update-a", "CachyMonitor-update-b", "autre"))
    for d in (vieux, recent, autre):
        d.mkdir()
    ancien = time.time() - 7200
    os.utime(vieux, (ancien, ancien))
    os.utime(autre, (ancien, ancien))
    updater.purge_old_downloads()
    assert not vieux.exists() and recent.exists() and autre.exists()
