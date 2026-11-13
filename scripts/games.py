#!/usr/bin/env python3
'''
Manage the games that ship with the casino. Games live in their own repos (local or remote); the
casino records which tagged version of each it ships in games.lock, and releases carry them as a
bundle, so no game needs a GitHub repo of its own.

    python scripts/games.py list                         what's locked vs installed
    python scripts/games.py set craps v1.2.0             lock a new version (or a new game, with --source)
    python scripts/games.py set keno v1.0.0 --source ~/Documents/Misc/casino-games/keno
    python scripts/games.py sync                         rebuild plugins/ from the locked versions
    python scripts/games.py bundle                       build dist/games-<version>.tar.gz, record its checksum
    python scripts/games.py release                      bundle, commit, tag, push, publish the GitHub release

`release` publishes two downloads: terminal-casino-<version>.zip (the casino with every game,
ready to run) and games-<version>.tar.gz (the games alone, which a cloned casino downloads on first
launch). Bundles are reproducible: the same game tags always give the same checksum.

Author: Ian Jackson
'''

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from casino import __version__                                   # noqa: E402
from casino.bundle import LOCK_FILE, MARKER, PLUGINS_DIR, installed, load_lock   # noqa: E402

DIST = ROOT / "dist"
EXCLUDE_DIRS = {".github", "tests", "test", "old", "results", "logs", "saves", "profiles", "__pycache__"}
EXCLUDE_FILES = {".gitignore", ".gitattributes", ".DS_Store"}
FIXED_MTIME = 946684800                                           # 2000-01-01: bundles are reproducible


def run(*cmd, cwd=None, capture=True) -> str:
    res = subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True)
    if res.returncode:
        sys.exit(f"✖ {' '.join(cmd)}\n{res.stderr.strip()}")
    return res.stdout


def save_lock(lock: dict) -> None:
    LOCK_FILE.write_text(json.dumps(lock, indent=4) + "\n")


#== Reading a game at a tag ==#

def game_files(key: str, game: dict) -> list:
    '''[(relative path, bytes, executable)] for a game at its locked tag, minus dev-only files.'''
    src, tag = game["source"], game["tag"]
    with tempfile.TemporaryDirectory() as tmp:
        if re.match(r"^(https?|git|ssh)://|^git@", src):
            repo = Path(tmp) / "src"
            run("git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1", "--branch", tag, src, str(repo))
        else:
            repo = Path(src).expanduser()
            if not (repo / ".git").exists():
                sys.exit(f"✖ {key}: {repo} isn't a git repo")
        if subprocess.run(["git", "-C", str(repo), "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
                          capture_output=True).returncode:
            sys.exit(f"✖ {key}: tag {tag} doesn't exist in {src}")
        raw = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", tag], capture_output=True).stdout
    files = []
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        for m in tar.getmembers():
            parts = Path(m.name).parts
            if not m.isfile() or any(p in EXCLUDE_DIRS for p in parts[:-1]) or parts[-1] in EXCLUDE_FILES:
                continue
            files.append((m.name, tar.extractfile(m).read(), bool(m.mode & 0o111)))
    if not any(name == "plugin.py" for name, _, _ in files):
        sys.exit(f"✖ {key} {tag}: no plugin.py at the root")
    return sorted(files)


#== Commands ==#

def cmd_list(_args) -> None:
    lock = load_lock()
    print(f"Terminal Casino {__version__}   bundle: {(lock.get('bundle') or {}).get('version', 'none yet')}")
    for key, game in (lock.get("games") or {}).items():
        marker = installed(key)
        state = ("not installed" if not (PLUGINS_DIR / key).exists()
                 else f"installed {marker['tag']}" if marker else "local checkout (not managed)")
        flag = "" if marker and marker["tag"] == game["tag"] else "  ←" if marker else ""
        print(f"  {key:14} {game['tag']:9} {state:28} {game['source']}{flag}")


def install(key: str, game: dict, force: bool = False) -> None:
    dest = PLUGINS_DIR / key
    if dest.exists() and installed(key) is None and any(dest.iterdir()) and not force:
        print(f"  {key}: {dest} is a local checkout, left alone (use --force to replace it)")
        return
    files = game_files(key, game)
    with tempfile.TemporaryDirectory(dir=PLUGINS_DIR.parent) as tmp:
        new = Path(tmp) / key
        for name, data, exe in files:
            path = new / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            if exe:
                path.chmod(0o755)
        for keep in ("logs", "saves"):              # a game's own logs and saves survive upgrades
            if (dest / keep).is_dir():
                shutil.copytree(dest / keep, new / keep)
        (new / MARKER).write_text(json.dumps({"key": key, "version": game["version"], "tag": game["tag"]}, indent=2))
        if dest.exists():
            shutil.rmtree(dest)
        PLUGINS_DIR.mkdir(exist_ok=True)
        shutil.move(str(new), str(dest))
    print(f"  {key}: installed {game['tag']} ({len(files)} files)")


def cmd_sync(args) -> None:
    lock = load_lock()
    for key, game in lock["games"].items():
        if not args.keys or key in args.keys:
            install(key, game, force=args.force)


def cmd_set(args) -> None:
    lock = load_lock()
    games = lock.setdefault("games", {})
    game = dict(games.get(args.key) or {})
    if args.source:
        src = str(Path(args.source).expanduser())
        game["source"] = src.replace(str(Path.home()), "~", 1) if src.startswith(str(Path.home())) else src
    if "source" not in game:
        sys.exit(f"✖ {args.key} isn't in games.lock yet: give its repo with --source")
    game["tag"] = args.tag
    game["version"] = args.tag.lstrip("v")
    files = game_files(args.key, game)                 # validates the tag and plugin.py
    meta = re.search(rb'"name"\s*:\s*"([^"]+)"', dict((n, d) for n, d, _ in files)["plugin.py"])
    game["name"] = args.name or (meta.group(1).decode() if meta else args.key)
    games[args.key] = game
    lock["games"] = dict(sorted(games.items()))
    save_lock(lock)
    print(f"games.lock: {args.key} → {args.tag}")
    install(args.key, game, force=True)


def build_bundle(lock: dict) -> tuple:
    '''Deterministic tar.gz of every locked game: (bytes, sha256).'''
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for key, game in lock["games"].items():
            seen_dirs = set()
            for name, data, exe in game_files(key, game):
                path = f"{key}/{name}"
                for parent in list(Path(path).parents)[::-1][1:]:
                    if str(parent) not in seen_dirs:
                        seen_dirs.add(str(parent))
                        info = tarfile.TarInfo(str(parent))
                        info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o755, FIXED_MTIME
                        tar.addfile(info)
                info = tarfile.TarInfo(path)
                info.size, info.mode, info.mtime = len(data), 0o755 if exe else 0o644, FIXED_MTIME
                tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(raw.getvalue())
    data = out.getvalue()
    return data, hashlib.sha256(data).hexdigest()


def cmd_bundle(_args) -> Path:
    lock = load_lock()
    data, sha = build_bundle(lock)
    DIST.mkdir(exist_ok=True)
    path = DIST / f"games-{__version__}.tar.gz"
    path.write_bytes(data)
    lock["bundle"] = {"version": __version__, "sha256": sha, "size": len(data)}
    save_lock(lock)
    print(f"{path.relative_to(ROOT)}: {len(lock['games'])} games, {len(data) // 1024} KB, sha256 {sha[:16]}…")
    return path


def build_app_zip(bundle_path: Path) -> Path:
    '''terminal-casino-<version>.zip: the casino at its release tag plus every game, ready to run.'''
    prefix = f"terminal-casino-{__version__}"
    path = DIST / f"{prefix}.zip"
    casino = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", f"v{__version__}"],
                            capture_output=True).stdout
    lock = load_lock()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        with tarfile.open(fileobj=io.BytesIO(casino)) as tar:
            for m in tar.getmembers():
                if m.isfile():
                    z.writestr(f"{prefix}/{m.name}", tar.extractfile(m).read())
        with tarfile.open(bundle_path, "r:gz") as tar:
            for m in tar.getmembers():
                if m.isfile():
                    z.writestr(f"{prefix}/plugins/{m.name}", tar.extractfile(m).read())
        for key, game in lock["games"].items():
            z.writestr(f"{prefix}/plugins/{key}/{MARKER}",
                       json.dumps({"key": key, "version": game["version"], "tag": game["tag"]}, indent=2))
    return path


def release_notes() -> str:
    text = (ROOT / "CHANGELOG.md").read_text()
    m = re.search(rf"^## \[{re.escape(__version__)}\][^\n]*\n(.*?)(?=^## \[|^\[)", text, re.S | re.M)
    notes = m.group(1).strip() if m else f"Terminal Casino {__version__}."
    return notes + ("\n\n**Download** `terminal-casino-" + __version__ + ".zip`, unzip it and run `python3 main.py`. "
                    "It includes every game. A `git clone` of the repo downloads the games automatically on first launch.")


def cmd_release(args) -> None:
    tag = f"v{__version__}"
    if run("git", "-C", str(ROOT), "status", "--porcelain").strip():
        sys.exit("✖ commit your changes first: the release is built from a clean tree")
    if run("git", "-C", str(ROOT), "tag", "--list", tag).strip():
        sys.exit(f"✖ {tag} already exists: bump casino/__init__.py first")
    if run("git", "-C", str(ROOT), "branch", "--show-current").strip() != "main":
        sys.exit("✖ release from main")
    bundle = cmd_bundle(args)
    if args.dry_run:
        print("dry run: games.lock updated but not committed; nothing tagged or published")
        return
    run("git", "-C", str(ROOT), "add", "games.lock")
    if run("git", "-C", str(ROOT), "status", "--porcelain").strip():
        run("git", "-C", str(ROOT), "commit", "-q", "-m",
            f"Lock the games bundle for {__version__}\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    run("git", "-C", str(ROOT), "tag", "-a", tag, "-m", f"Terminal Casino {__version__}")
    run("git", "-C", str(ROOT), "push", "-q", "origin", "main", tag)
    app = build_app_zip(bundle)
    notes = DIST / "notes.md"
    notes.write_text(release_notes())
    flags = ["--prerelease"] if "-" in __version__ else []
    run("gh", "release", "create", tag, str(app), str(bundle), "--title", f"Terminal Casino {__version__}",
        "--notes-file", str(notes), *flags, cwd=ROOT)
    print(f"released {tag}: {app.name} ({app.stat().st_size // 1024} KB) and {bundle.name}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    p = sub.add_parser("sync"); p.add_argument("keys", nargs="*"); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_sync)
    p = sub.add_parser("set"); p.add_argument("key"); p.add_argument("tag")
    p.add_argument("--source"); p.add_argument("--name"); p.set_defaults(fn=cmd_set)
    sub.add_parser("bundle").set_defaults(fn=cmd_bundle)
    p = sub.add_parser("release"); p.add_argument("--dry-run", action="store_true"); p.set_defaults(fn=cmd_release)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
