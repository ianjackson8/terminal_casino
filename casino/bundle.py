'''
Games travel with the casino as a bundle attached to each GitHub release, so they don't each need
a GitHub repo of their own.

    games.lock                       which version of each game this casino version ships with
    games-<version>.tar.gz           the games, attached to the casino's release (checksum in games.lock)
    plugins/<key>/.bundle.json       what's installed in each game folder

On launch, `ensure_games()` installs any game that's missing or out of date from the release's
bundle: download, verify the checksum, unpack. Game folders without a .bundle.json (a developer's
own checkout, say) are never touched. Building and publishing bundles is scripts/games.py.

Author: Ian Jackson
'''

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
LOCK_FILE = ROOT / "games.lock"
PLUGINS_DIR = ROOT / "plugins"
MARKER = ".bundle.json"
NO_DOWNLOAD_ENV = "TERMINAL_CASINO_NO_DOWNLOAD"


def load_lock(path: Path = LOCK_FILE) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def installed(key: str, plugins_dir: Path = PLUGINS_DIR) -> Optional[dict]:
    '''The .bundle.json of an installed game, or None (not installed, or not managed by bundles).'''
    try:
        return json.loads((plugins_dir / key / MARKER).read_text())
    except (OSError, ValueError):
        return None


def needed(lock: dict, plugins_dir: Path = PLUGINS_DIR) -> List[str]:
    '''Locked games that are missing, or installed from a bundle at a different version.'''
    out = []
    for key, game in (lock.get("games") or {}).items():
        folder = plugins_dir / key
        marker = installed(key, plugins_dir)
        if marker is None:
            if folder.exists() and any(folder.iterdir()):
                continue                    # someone's own checkout: leave it alone
            out.append(key)
        elif marker.get("tag") != game.get("tag"):
            out.append(key)
    return out


def bundle_url(lock: dict, version: str) -> str:
    repo = lock.get("repo", "ianjackson8/terminal_casino")
    return f"https://github.com/{repo}/releases/download/v{version}/games-{version}.tar.gz"


def _safe_members(tar: tarfile.TarFile, keys: List[str]):
    '''Regular files and folders under <key>/ for the wanted keys; nothing absolute, nothing escaping.'''
    wanted = set(keys)
    for m in tar.getmembers():
        parts = Path(m.name).parts
        if not parts or parts[0] not in wanted or m.name.startswith(("/", "\\")) or ".." in parts:
            continue
        if not (m.isfile() or m.isdir()):
            continue                        # no links, devices or fifos
        yield m


def install_from_tarball(data: bytes, keys: List[str], lock: dict, plugins_dir: Path = PLUGINS_DIR) -> List[str]:
    '''Unpack the given games from a bundle into plugins/, replacing older bundle installs.'''
    done = []
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = list(_safe_members(tar, keys))
        try:
            tar.extractall(tmp, members=members, filter="data")
        except TypeError:                   # Pythons without extraction filters; members are already vetted
            tar.extractall(tmp, members=members)
        for key in keys:
            src = Path(tmp) / key
            if not (src / "plugin.py").exists():
                continue
            dest = plugins_dir / key
            if dest.exists():
                if installed(key, plugins_dir) is None and any(dest.iterdir()):
                    continue                # never replace a folder we didn't install
                _keep_user_data(dest, src)
                shutil.rmtree(dest)
            game = lock["games"][key]
            (src / MARKER).write_text(json.dumps({"key": key, "version": game["version"], "tag": game["tag"]}, indent=2))
            plugins_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            done.append(key)
    return done


def _keep_user_data(old: Path, new: Path) -> None:
    '''Carry a game's logs and saves over when it's upgraded in place.'''
    for name in ("logs", "saves"):
        if (old / name).is_dir() and not (new / name).exists():
            shutil.copytree(old / name, new / name)


def download(url: str, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "terminal-casino"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def ensure_games(version: str, log: Callable[[str, str], None] = lambda level, msg: None,
                 plugins_dir: Path = PLUGINS_DIR, lock: Optional[dict] = None,
                 fetch: Callable[[str], bytes] = download) -> Dict[str, List[str]]:
    '''
    Install whatever games this casino version is missing from its release bundle.
    Returns {"installed": [...], "missing": [...]}. Never raises: a failed download is logged and
    the casino carries on with the games it has.
    '''
    lock = load_lock() if lock is None else lock
    keys = needed(lock, plugins_dir)
    if not keys:
        return {"installed": [], "missing": []}
    expected = (lock.get("bundle") or {}).get("sha256")
    if os.environ.get(NO_DOWNLOAD_ENV) or not expected or (lock.get("bundle") or {}).get("version") != version:
        return {"installed": [], "missing": keys}
    url = bundle_url(lock, version)
    try:
        data = fetch(url)
    except Exception as err:                # offline, firewall, release not published yet…
        log("warn", f"Couldn't download the games for {version} ({err}). "
                    f"{len(keys)} game{'s' if len(keys) != 1 else ''} not installed; they'll install next time.")
        return {"installed": [], "missing": keys}
    if hashlib.sha256(data).hexdigest() != expected:
        log("error", "The downloaded games bundle failed its checksum, so it wasn't installed.")
        return {"installed": [], "missing": keys}
    try:
        done = install_from_tarball(data, keys, lock, plugins_dir)
    except (OSError, tarfile.TarError) as err:
        log("error", f"Couldn't unpack the games bundle: {err}")
        return {"installed": [], "missing": keys}
    if done:
        names = ", ".join(lock["games"][k].get("name", k) for k in done)
        log("info", f"Installed {names} ({len(data) // 1024} KB) for Terminal Casino {version}.")
    return {"installed": done, "missing": [k for k in keys if k not in done]}
