"""CachyMonitor : mise à jour depuis l'application (sans Qt, donc testable).

Principe : la dernière release GitHub est interrogée ; si son numéro dépasse
APP_VERSION, l'installateur `CachyMonitor-Setup-X.Y.Z.exe` joint à la release est
téléchargé dans le dossier temporaire de l'utilisateur, son empreinte SHA-256 est
comparée à celle que GitHub publie pour ce fichier, puis il est lancé en mode
silencieux. Sans empreinte publiée, rien n'est installé automatiquement : l'appli
renvoie vers la page de la release.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from .debug import debug_exc

REPO = "YOUNES-2-wq/cachymonitor"
API_URL = "https://api.github.com/repos/%s/releases/latest" % REPO
RELEASES_URL = "https://github.com/%s/releases/latest" % REPO
USER_AGENT = "CachyMonitor-updater"
ASSET_RE = re.compile(r"^CachyMonitor-Setup-[0-9][0-9A-Za-z.\-]*\.exe$")
CHECK_TIMEOUT_S = 10
DOWNLOAD_TIMEOUT_S = 30
MAX_SIZE = 500 * 1024 * 1024      # garde-fou : l'installateur pèse une cinquantaine de Mo
_VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+){0,3})$")


class UpdateError(Exception):
    """Échec de téléchargement ou de vérification (message pour le journal)."""


class UpdateCancelled(UpdateError):
    """Téléchargement interrompu par l'utilisateur."""


@dataclass(frozen=True)
class Release:
    version: str            # « 1.7.1 »
    page_url: str           # page de la release (repli manuel)
    asset_url: str = ""     # installateur, vide si la release n'en porte pas
    sha256: str = ""        # empreinte publiée par GitHub, vide si absente
    size: int = 0

    @property
    def installable(self):
        return bool(self.asset_url and self.sha256)


def parse_version(text):
    """« v1.7.1 » -> (1, 7, 1) ; None si ce n'est pas un numéro de version simple
    (une préversion comme « 1.8.0-beta » est donc ignorée)."""
    match = _VERSION_RE.match(str(text or "").strip())
    if not match:
        return None
    return tuple(int(n) for n in match.group(1).split("."))


def is_newer(candidate, current):
    """Vrai si `candidate` est un numéro valide strictement supérieur à `current`.
    Les longueurs sont alignées : 1.7 et 1.7.0 sont la même version."""
    a, b = parse_version(candidate), parse_version(current)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def _github_host(url):
    parts = urlparse(url)
    return parts.scheme == "https" and parts.hostname == "github.com"


def release_from_json(data):
    """Release utilisable déduite de la réponse de l'API, ou None (brouillon,
    préversion, numéro illisible). Ne vérifie pas que c'est une nouveauté."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if parse_version(tag) is None:
        return None
    version = tag.lstrip("v")
    page = str(data.get("html_url") or "")
    if not _github_host(page):
        page = RELEASES_URL
    asset_url, sha256, size = "", "", 0
    for asset in data.get("assets") or []:
        if not isinstance(asset, dict) or not ASSET_RE.match(str(asset.get("name") or "")):
            continue
        url = str(asset.get("browser_download_url") or "")
        digest = str(asset.get("digest") or "")
        if _github_host(url) and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
            asset_url, sha256 = url, digest.split(":", 1)[1].lower()
            size = asset.get("size") if isinstance(asset.get("size"), int) else 0
            break
    return Release(version, page, asset_url, sha256, size)


def fetch_latest():
    """Dernière release publiée (Release), ou None si elle est illisible ou si le
    réseau échoue : une vérification ratée ne doit jamais gêner l'appli."""
    request = urllib.request.Request(API_URL, headers={
        "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT_S) as response:
            return release_from_json(json.loads(response.read(2_000_000)))
    except Exception:
        debug_exc("mise à jour : vérification")
        return None


def check_for_update(current):
    """Release plus récente que `current`, sinon None."""
    release = fetch_latest()
    return release if release and is_newer(release.version, current) else None


def download(release, progress=None, cancelled=None):
    """Télécharge l'installateur, vérifie son SHA-256 et renvoie son chemin.

    `progress(octets_lus, total)` est appelé au fil du téléchargement ;
    `cancelled()` vrai l'interrompt. Lève UpdateError au moindre doute, après
    avoir effacé ce qui a été écrit. Le dossier est créé dans le %TEMP% de
    l'utilisateur, inaccessible aux autres comptes.
    """
    if not release.installable:
        raise UpdateError("release sans installateur ou sans empreinte")
    folder = tempfile.mkdtemp(prefix="CachyMonitor-update-")
    path = os.path.join(folder, os.path.basename(urlparse(release.asset_url).path))
    try:
        request = urllib.request.Request(release.asset_url, headers={"User-Agent": USER_AGENT})
        digest = hashlib.sha256()
        done = 0
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response, \
                open(path, "wb") as out:
            total = int(response.headers.get("Content-Length") or release.size or 0)
            if total > MAX_SIZE:
                raise UpdateError("fichier anormalement gros (%d octets)" % total)
            while True:
                if cancelled and cancelled():
                    raise UpdateCancelled()
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_SIZE:
                    raise UpdateError("fichier anormalement gros")
                digest.update(chunk)
                out.write(chunk)
                if progress:
                    progress(done, total)
        if digest.hexdigest() != release.sha256:
            raise UpdateError("empreinte SHA-256 différente de celle publiée par GitHub")
        return path
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def purge_old_downloads(max_age_s=3600):
    """Efface les dossiers d'installateurs laissés par d'anciennes mises à jour.
    Un installateur encore en cours ne peut pas être effacé (fichier verrouillé) et
    les dossiers de moins d'une heure sont gardés : au pire il en reste un."""
    root = tempfile.gettempdir()
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        folder = os.path.join(root, name)
        try:
            if (name.startswith("CachyMonitor-update-") and os.path.isdir(folder)
                    and time.time() - os.path.getmtime(folder) > max_age_s):
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


def launch_installer(path):
    """Lance l'installateur en mode silencieux (barre de progression visible, aucune
    question) et demande à Inno Setup de fermer l'appli puis de la relancer
    (/RELAUNCH=1, géré par CachyMonitor.iss). ShellExecute plutôt que Popen : si
    l'installation d'origine est « pour tous les utilisateurs », Windows doit pouvoir
    afficher l'invite d'administrateur (UAC). Renvoie True si Windows l'a démarré."""
    import ctypes
    shell_execute = ctypes.windll.shell32.ShellExecuteW
    shell_execute.restype = ctypes.c_void_p     # HINSTANCE : 64 bits, sinon tronqué
    result = shell_execute(None, "open", path,
                           "/SILENT /SP- /NOCANCEL /CLOSEAPPLICATIONS /RELAUNCH=1",
                           os.path.dirname(path), 1)
    return (result or 0) > 32
