'''
Compliance checks for game plugins, based on docs/GAME_SPEC.md.

Used two ways:
  - at startup by casino.loader: any error means the plugin is not loaded
  - by developers: `python -m casino.check <game folder or key>` prints a full report

Each Finding is an error (spec MUST broken: the game is blocked), a warning (SHOULD, or a
heuristic that can't be proven), or ok (a check that passed, shown in the dev report).

Author: Ian Jackson
'''

from __future__ import annotations

import ast
import builtins
import importlib.util
import inspect
import io
import math
import re
import subprocess
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

ERROR, WARN, OK = "error", "warn", "ok"

KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
VERSION_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+")

META_FIELDS = {"name", "description", "min_bet", "version", "author", "api"}
HEAVY_MODULES = {"torch", "tensorflow", "jax", "numpy", "pandas", "scipy", "sklearn", "matplotlib",
                 "cv2", "pygame", "transformers"}
GENERIC_MODULES = {"tui", "ui", "utils", "util", "helpers", "config", "settings", "strategy", "game",
                   "main", "constants", "models", "common", "core", "app", "player", "cards", "deck"}
RESERVED_MODULES = {"casino", "plugins"}
SKIP_DIRS = {"tests", "test", "old", "venv", ".venv", "env", "myenv", "__pycache__", "docs",
             "node_modules", "build", "dist"}
IMPORT_SLOW_S = 0.3
NAME_MAX, DESC_MAX = 24, 60


@dataclass
class Finding:
    level: str      # ERROR / WARN / OK
    rule: str       # spec section, e.g. "§3.1"
    check: str      # short check name
    message: str


@dataclass
class Report:
    key: str
    path: Path
    findings: List[Finding] = field(default_factory=list)
    module: object = None           # the imported plugin module, if the import worked
    modules: Set[str] = field(default_factory=set)   # top-level module names the game provides

    def add(self, level: str, rule: str, check: str, message: str) -> None:
        self.findings.append(Finding(level, rule, check, message))

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.level == ERROR]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.level == WARN]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def meta(self) -> dict:
        meta = getattr(self.module, "PLUGIN_META", None)
        return meta if isinstance(meta, dict) else {}


#== Helpers ==#

def top_level_modules(path: Path) -> Set[str]:
    '''Module names a game would put on sys.path: its top-level .py files and packages.'''
    mods = set()
    for entry in path.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.is_file() and entry.suffix == ".py":
            stem = entry.stem
            if stem == "plugin" or stem.startswith("test_") or stem in ("conftest", "setup"):
                continue
            mods.add(stem)
        elif entry.is_dir() and entry.name not in SKIP_DIRS and (entry / "__init__.py").exists():
            mods.add(entry.name)
    return mods


class _ExitFinder(ast.NodeVisitor):
    '''Finds sys.exit / exit / quit / os._exit / raise SystemExit outside `if __name__ == "__main__":`.'''

    def __init__(self):
        self.hits: List[tuple] = []     # (line, text)
        self._main_guard = 0

    @staticmethod
    def _is_main_guard(node: ast.If) -> bool:
        t = node.test
        return (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name) and t.left.id == "__name__"
                and any(isinstance(c, ast.Constant) and c.value == "__main__" for c in t.comparators))

    def visit_If(self, node: ast.If) -> None:
        if self._is_main_guard(node):
            self._main_guard += 1
            for child in node.body:
                self.visit(child)
            self._main_guard -= 1
            for child in node.orelse:
                self.visit(child)
        else:
            self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        f = node.func
        name = None
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if (f.value.id, f.attr) in (("sys", "exit"), ("os", "_exit")):
                name = f"{f.value.id}.{f.attr}()"
        elif isinstance(f, ast.Name) and f.id in ("exit", "quit"):
            name = f"{f.id}()"
        if name and not self._main_guard:
            self.hits.append((node.lineno, name))
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        exc = node.exc
        target = exc.func if isinstance(exc, ast.Call) else exc
        if isinstance(target, ast.Name) and target.id == "SystemExit" and not self._main_guard:
            self.hits.append((node.lineno, "raise SystemExit"))
        self.generic_visit(node)


def _exit_calls(tree: ast.AST) -> List[tuple]:
    finder = _ExitFinder()
    finder.visit(tree)
    return finder.hits


def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=5)


#== The checks ==#

def _check_structure(r: Report) -> Optional[ast.AST]:
    if not r.path.is_dir():
        r.add(ERROR, "§2", "Folder", f"{r.path} is not a folder")
        return None
    plugin_py = r.path / "plugin.py"
    if not plugin_py.exists():
        r.add(ERROR, "§2", "plugin.py", "no plugin.py at the root of the game folder")
        return None
    r.add(OK, "§2", "plugin.py", "found at the folder root")
    if KEY_RE.match(r.key):
        r.add(OK, "§2", "Plugin key", f"'{r.key}' is lowercase snake_case")
    else:
        suggestion = re.sub(r"[^a-z0-9]+", "_", r.key.lower()).strip("_") or "my_game"
        r.add(ERROR, "§2", "Plugin key", f"'{r.key}' must be lowercase snake_case, e.g. '{suggestion}'")
    try:
        tree = ast.parse(plugin_py.read_text(), filename=str(plugin_py))
    except SyntaxError as err:
        r.add(ERROR, "§3", "Syntax", f"plugin.py line {err.lineno}: {err.msg}")
        return None
    hits = _exit_calls(tree)
    for line, text in hits:
        r.add(ERROR, "§3.2", "No exits", f"plugin.py:{line} calls {text}; return the balance instead")
    if not hits:
        r.add(OK, "§3.2", "No exits", "plugin.py never calls sys.exit / exit / quit")
    return tree


def _check_modules(r: Report, taken: Dict[str, str]) -> None:
    r.modules = top_level_modules(r.path)
    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    problems = False
    for mod in sorted(r.modules):
        if mod in RESERVED_MODULES:
            r.add(ERROR, "§4.3", "Module names", f"'{mod}' is reserved by the casino; rename it")
            problems = True
        elif mod in stdlib:
            r.add(ERROR, "§4.3", "Module names", f"'{mod}' shadows the Python standard library; rename it")
            problems = True
        elif mod in taken:
            r.add(ERROR, "§4.3", "Module names", f"'{mod}' is also provided by plugin '{taken[mod]}'; "
                                                 "one of them must rename it")
            problems = True
        elif mod in GENERIC_MODULES:
            r.add(WARN, "§4.3", "Module names", f"'{mod}' is a generic name likely to collide with another "
                                                "game; prefix it or move it into a package")
            problems = True
    if not problems:
        r.add(OK, "§4.3", "Module names", f"{len(r.modules)} module(s), no collisions")


def _check_import(r: Report, module_name: str) -> None:
    spec = importlib.util.spec_from_file_location(module_name, r.path / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    out, err = io.StringIO(), io.StringIO()
    real_input = builtins.input

    def no_input(*_a, **_k):
        raise RuntimeError("input() was called while importing plugin.py")

    before = set(sys.modules)
    sys.modules[module_name] = module
    started = time.perf_counter()
    builtins.input = no_input
    try:
        with redirect_stdout(out), redirect_stderr(err):
            spec.loader.exec_module(module)
    except SystemExit:
        sys.modules.pop(module_name, None)
        r.add(ERROR, "§3.2", "Import", "plugin.py exits at import time (SystemExit)")
        return
    except Exception as exc:
        sys.modules.pop(module_name, None)
        r.add(ERROR, "§4.4", "Import", f"plugin.py failed to import: {type(exc).__name__}: {exc}")
        return
    finally:
        builtins.input = real_input
    elapsed = time.perf_counter() - started
    r.module = module

    printed = out.getvalue() + err.getvalue()
    if printed:
        first = printed.strip().splitlines()[0][:60] if printed.strip() else ""
        r.add(ERROR, "§4.4", "Quiet import", f"plugin.py prints at import time{': ' + repr(first) if first else ''}")
    else:
        r.add(OK, "§4.4", "Quiet import", "no output at import time")

    heavy = sorted({m.split(".")[0] for m in set(sys.modules) - before} & HEAVY_MODULES)
    if heavy:
        r.add(ERROR, "§4.4", "Lazy imports", f"imports {', '.join(heavy)} at module level; move it inside run()")
    elif elapsed > IMPORT_SLOW_S:
        r.add(WARN, "§4.4", "Import time", f"plugin.py took {elapsed:.2f}s to import (aim for under {IMPORT_SLOW_S}s)")
    else:
        r.add(OK, "§4.4", "Import time", f"{elapsed * 1000:.0f} ms, no heavy modules")


def _check_meta(r: Report) -> None:
    meta = getattr(r.module, "PLUGIN_META", None)
    if meta is None:
        r.add(ERROR, "§3.1", "PLUGIN_META", "missing")
        return
    if not isinstance(meta, dict):
        r.add(ERROR, "§3.1", "PLUGIN_META", f"must be a dict, not {type(meta).__name__}")
        return
    before = len(r.errors)

    name = meta.get("name")
    if not isinstance(name, str) or not name.strip():
        r.add(ERROR, "§3.1", "name", "required, a non-empty string")
    elif len(name) > NAME_MAX:
        r.add(WARN, "§3.1", "name", f"{len(name)} characters; keep it to {NAME_MAX} or fewer")

    desc = meta.get("description")
    if not isinstance(desc, str) or not desc.strip():
        r.add(ERROR, "§3.1", "description", "required, a non-empty string")
    elif len(desc) > DESC_MAX:
        r.add(WARN, "§3.1", "description", f"{len(desc)} characters; aim for {DESC_MAX} or fewer")

    bet = meta.get("min_bet")
    if isinstance(bet, bool) or not isinstance(bet, (int, float)) or not math.isfinite(bet) or bet < 0:
        r.add(ERROR, "§3.1", "min_bet", f"required, a number >= 0 (got {bet!r})")

    version = meta.get("version")
    if not isinstance(version, str) or not SEMVER_RE.match(version):
        r.add(ERROR, "§2.1", "version", f"required, full semver like \"1.0.0\" (got {version!r})")

    unknown = sorted(set(meta) - META_FIELDS)
    if unknown:
        r.add(WARN, "§3.1", "PLUGIN_META", f"unknown field(s) {', '.join(unknown)}; typo?")
    if len(r.errors) == before:
        r.add(OK, "§3.1", "PLUGIN_META", f"{meta['name']} v{meta['version']}, min bet {meta['min_bet']}")


def _check_run(r: Report) -> None:
    run = getattr(r.module, "run", None)
    if not callable(run):
        r.add(ERROR, "§3.2", "run()", "missing; define run(player_name, balance) -> float")
        return
    try:
        inspect.signature(run).bind("Player", 100.0)
    except TypeError:
        r.add(ERROR, "§3.2", "run()", "must accept (player_name, balance) as positional arguments")
    except ValueError:
        r.add(WARN, "§3.2", "run()", "signature couldn't be inspected")
    else:
        r.add(OK, "§3.2", "run()", "accepts (player_name, balance)")


def _check_git(r: Report) -> None:
    version = r.meta.get("version")
    if not isinstance(version, str) or not SEMVER_RE.match(version):
        return
    try:
        top = _git(r.path, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.TimeoutExpired):
        r.add(OK, "§2.1", "Git tag", "git not available; tag checks skipped")
        return
    if top.returncode or Path(top.stdout.strip()).resolve() != r.path.resolve():
        r.add(OK, "§2.1", "Git tag", "plain folder (not its own git repo); tag checks skipped")
        return

    want = f"v{version}"
    at_head = _git(r.path, "tag", "--points-at", "HEAD").stdout.split()
    version_tags = [t for t in at_head if VERSION_TAG_RE.match(t)]
    if want in at_head:
        r.add(OK, "§2.1", "Git tag", f"HEAD is tagged {want}")
    elif version_tags:
        r.add(ERROR, "§2.1", "Git tag", f"HEAD is tagged {', '.join(version_tags)} but PLUGIN_META says {version}")
    elif _git(r.path, "rev-parse", "-q", "--verify", f"refs/tags/{want}").returncode == 0:
        r.add(ERROR, "§2.1", "Git tag", f"{want} is a different commit; bump the version, or check out {want}")
    else:
        r.add(WARN, "§2.1", "Git tag", f"this release isn't tagged; run: git tag -a {want} -m \"{r.meta.get('name', r.key)} {version}\"")

    if _git(r.path, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        r.add(WARN, "§2.1", "Clean tree", "uncommitted changes; this build doesn't match a release")


def _check_files(r: Report) -> None:
    for name, rule, why in (("requirements.txt", "§4.5", "list the game's dependencies"),
                            ("CHANGELOG.md", "§2.1", "one entry per version")):
        if (r.path / name).exists():
            r.add(OK, rule, name, "present")
        else:
            r.add(WARN, rule, name, f"missing ({why})")


def _check_source_exits(r: Report) -> None:
    '''Exit calls anywhere else in the game. Only warnings: we can't prove they're reachable from run().'''
    hits = []
    for path in sorted(r.path.rglob("*.py")):
        rel = path.relative_to(r.path)
        if rel.name == "plugin.py" and len(rel.parts) == 1:
            continue
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]):
            continue
        try:
            tree = ast.parse(path.read_text(errors="ignore"))
        except SyntaxError:
            continue
        hits += [(rel, line, text) for line, text in _exit_calls(tree)]
        if len(hits) > 20:
            break
    for rel, line, text in hits[:8]:
        r.add(WARN, "§3.2", "Exits in game code", f"{rel}:{line} calls {text}; make sure run() can't reach it")
    if len(hits) > 8:
        r.add(WARN, "§3.2", "Exits in game code", f"… and {len(hits) - 8} more")
    if not hits:
        r.add(OK, "§3.2", "Exits in game code", "no exit calls outside __main__ blocks")


def check_plugin(path: Path, key: Optional[str] = None, taken: Optional[Dict[str, str]] = None,
                 deep: bool = False) -> Report:
    '''
    Run the compliance checks on one game folder.
      key:   the plugin key it will be installed as (default: the folder name)
      taken: module name -> plugin key, for modules already provided by other plugins
      deep:  also run slower, warning-only checks (used by the dev CLI, skipped at startup)
    '''
    path = Path(path)
    r = Report(key=key or path.name, path=path)
    if _check_structure(r) is None:
        return r
    _check_modules(r, taken or {})
    _check_import(r, f"plugins.{r.key}.plugin")
    if r.module is not None:
        _check_meta(r)
        _check_run(r)
        _check_git(r)
    else:
        r.add(WARN, "§3", "Skipped", "PLUGIN_META, run() and git checks need plugin.py to import; fix that first")
    if deep:
        _check_files(r)
        _check_source_exits(r)
    return r
